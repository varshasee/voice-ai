import os
import certifi

os.environ["SSL_CERT_FILE"] = certifi.where()

import logging
import json
from pathlib import Path
from dotenv import load_dotenv

from livekit import agents, api
from livekit.agents import AgentSession, Agent, RoomInputOptions
from livekit.plugins import (
    openai,
    cartesia,
    deepgram,
    noise_cancellation,
    silero,
    sarvam,
)
from livekit.agents import llm
from typing import Optional

load_dotenv(dotenv_path=Path(__file__).parent / ".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("outbound-agent")

import config

# CRITICAL: Set to False for production (actual calls), True for testing without telephony
TEST_MODE_DISABLE_TELEPHONY = False


def _build_tts(config_provider: str = None, config_voice: str = None):
    """Build TTS provider - defaults to Sarvam for Indian voice"""
    provider = (config_provider or os.getenv("TTS_PROVIDER", config.DEFAULT_TTS_PROVIDER)).lower()

    if config_voice and config_voice.lower() in ["anushka", "aravind", "amartya", "dhruv"]:
        provider = "sarvam"

    if provider == "cartesia":
        model = os.getenv("CARTESIA_TTS_MODEL", config.CARTESIA_MODEL)
        voice = os.getenv("CARTESIA_TTS_VOICE", config.CARTESIA_VOICE)
        logger.info(f"Using Cartesia TTS | model={model} | voice={voice}")
        return cartesia.TTS(model=model, voice=voice)

    if provider == "sarvam":
        model = os.getenv("SARVAM_TTS_MODEL", config.SARVAM_MODEL)
        voice = config_voice or os.getenv("SARVAM_VOICE", config.DEFAULT_TTS_VOICE)
        language = os.getenv("SARVAM_LANGUAGE", config.SARVAM_LANGUAGE)

        logger.info(f"✅ Using Sarvam TTS | model={model} | voice={voice} | language={language}")

        if not os.getenv("SARVAM_API_KEY"):
            logger.error("❌ SARVAM_API_KEY is missing. Sarvam TTS may fail.")
            logger.error("   Add SARVAM_API_KEY to your .env file")

        return sarvam.TTS(model=model, speaker=voice, target_language_code=language)

    if provider == "deepgram":
        model = os.getenv("DEEPGRAM_TTS_MODEL", "aura-asteria-en")
        logger.info(f"Using Deepgram TTS | model={model}")
        return deepgram.TTS(model=model)

    model = os.getenv("OPENAI_TTS_MODEL", "tts-1")
    voice = config_voice or os.getenv("OPENAI_TTS_VOICE", config.DEFAULT_TTS_VOICE)
    logger.info(f"Using OpenAI TTS | model={model} | voice={voice}")
    return openai.TTS(model=model, voice=voice)


def _build_llm(config_provider: str = None):
    """Build LLM provider - defaults to Groq"""
    provider = (config_provider or os.getenv("LLM_PROVIDER", config.DEFAULT_LLM_PROVIDER)).lower()

    if provider == "groq":
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            logger.error("❌ GROQ_API_KEY is missing. Add it to .env file")
            raise ValueError("GROQ_API_KEY not found in environment")
        
        logger.info("✅ Using Groq LLM")
        return openai.LLM(
            base_url="https://api.groq.com/openai/v1",
            api_key=api_key,
            model=os.getenv("GROQ_MODEL", config.GROQ_MODEL),
            temperature=float(os.getenv("GROQ_TEMPERATURE", str(config.GROQ_TEMPERATURE))),
        )

    logger.info("Using OpenAI LLM")
    return openai.LLM(model=config.DEFAULT_LLM_MODEL)


class TransferFunctions(llm.ToolContext):
    """Handle call transfers to human agents"""
    def __init__(self, ctx: agents.JobContext, phone_number: str = None):
        super().__init__(tools=[])
        self.ctx = ctx
        self.phone_number = phone_number

    @llm.function_tool(description="Look up lead details by phone number.")
    async def lookup_user(self, phone: str):
        logger.info(f"Looking up lead: {phone}")
        return "Lead found. Campaign: Divyasree Whispers of the Wind. Status: New lead."

    @llm.function_tool(description="Transfer the call to a human property expert or another phone number.")
    async def transfer_call(self, destination: Optional[str] = None):
        if destination is None:
            destination = config.DEFAULT_TRANSFER_NUMBER
            if not destination:
                return "Error: No default transfer number configured."

        if "@" not in destination:
            if config.SIP_DOMAIN:
                clean_dest = destination.replace("tel:", "").replace("sip:", "")
                destination = f"sip:{clean_dest}@{config.SIP_DOMAIN}"
            else:
                if not destination.startswith("tel:") and not destination.startswith("sip:"):
                    destination = f"tel:{destination}"
        elif not destination.startswith("sip:"):
            destination = f"sip:{destination}"

        participant_identity = None

        if self.phone_number:
            participant_identity = f"sip_{self.phone_number}"
        else:
            for participant in self.ctx.room.remote_participants.values():
                participant_identity = participant.identity
                break

        if not participant_identity:
            logger.error("Could not determine participant identity for transfer")
            return "Failed to transfer: could not identify the caller."

        try:
            logger.info(f"Transferring participant {participant_identity} to {destination}")
            await self.ctx.api.sip.transfer_sip_participant(
                api.TransferSIPParticipantRequest(
                    room_name=self.ctx.room.name,
                    participant_identity=participant_identity,
                    transfer_to=destination,
                    play_dialtone=False,
                )
            )
            return "Transfer initiated successfully."
        except Exception as e:
            logger.error(f"Transfer failed: {e}")
            return f"Error executing transfer: {e}"


class OutboundAssistant(Agent):
    """The AI voice agent - loads system prompt from config"""
    def __init__(self, tools: list) -> None:
        super().__init__(
            instructions=config.SYSTEM_PROMPT,
            tools=tools,
        )


async def entrypoint(ctx: agents.JobContext):
    """Main entrypoint for the agent"""
    logger.info(f"🚀 Connecting to room: {ctx.room.name}")
    logger.info(f"📄 Loaded config file: {config.__file__}")
    
    # Verify SYSTEM_PROMPT is loaded
    if not config.SYSTEM_PROMPT or len(config.SYSTEM_PROMPT) < 100:
        logger.error("❌ SYSTEM_PROMPT is empty or too short!")
        logger.error("   Check config.py - SYSTEM_PROMPT must be set")
        ctx.shutdown()
        return
    
    logger.info(f"✅ SYSTEM_PROMPT loaded ({len(config.SYSTEM_PROMPT)} characters)")
    logger.info(f"✅ INITIAL_GREETING: {config.INITIAL_GREETING[:100]}...")

    if TEST_MODE_DISABLE_TELEPHONY:
        logger.warning("⚠️  TEST MODE: Telephony disabled. No actual calls will be made.")

    phone_number = None
    config_dict = {}

    # Extract phone number from job metadata
    try:
        if ctx.job.metadata:
            data = json.loads(ctx.job.metadata)
            phone_number = data.get("phone_number")
            config_dict = data
    except Exception as e:
        logger.warning(f"No valid JSON metadata found in job: {e}")

    # Extract phone number from room metadata
    try:
        if ctx.room.metadata:
            data = json.loads(ctx.room.metadata)
            if data.get("phone_number"):
                phone_number = data.get("phone_number")
            config_dict.update(data)
    except Exception as e:
        logger.warning(f"No valid JSON metadata found in room: {e}")

    fnc_ctx = TransferFunctions(ctx, phone_number)

    # Log runtime configuration
    logger.info(f"📊 Runtime Config:")
    logger.info(f"   STT: {config.STT_PROVIDER} ({config.STT_MODEL})")
    logger.info(f"   LLM: {config_dict.get('model_provider') or config.DEFAULT_LLM_PROVIDER}")
    logger.info(f"   TTS: {config_dict.get('tts_provider') or config.DEFAULT_TTS_PROVIDER} / {config_dict.get('voice_id') or config.DEFAULT_TTS_VOICE}")

    # Build session with VAD (Voice Activity Detection)
    session = AgentSession(
        vad=silero.VAD.load(),  # ← CRITICAL: Detects when user stops speaking
        stt=deepgram.STT(model=config.STT_MODEL, language=config.STT_LANGUAGE),
        llm=_build_llm(config_dict.get("model_provider")),
        tts=_build_tts(config_dict.get("tts_provider"), config_dict.get("voice_id")),
    )

    # Start agent session
    await session.start(
        room=ctx.room,
        agent=OutboundAssistant(tools=list(fnc_ctx.function_tools.values())),
        room_input_options=RoomInputOptions(
            noise_cancellation=noise_cancellation.BVCTelephony(),
            close_on_disconnect=False,  # ← CRITICAL FIX: Don't close on user silence
        ),
    )

    should_dial = False

    # Determine if we need to make an outbound call
    if phone_number and not TEST_MODE_DISABLE_TELEPHONY:
        user_already_here = False

        for participant in ctx.room.remote_participants.values():
            if f"sip_{phone_number}" in participant.identity or "sip_" in participant.identity:
                user_already_here = True
                break

        if not user_already_here:
            should_dial = True
            logger.info(f"📞 User not in room. Will initiate dial-out to {phone_number}")
        else:
            logger.info("✅ User already in room. Agent will generate greeting only.")

    # CRITICAL SECTION: Make the outbound call and trigger greeting
    if should_dial:
        logger.info(f"📞 Initiating outbound SIP call to {phone_number}...")
        try:
            await ctx.api.sip.create_sip_participant(
                api.CreateSIPParticipantRequest(
                    room_name=ctx.room.name,
                    sip_trunk_id=config.SIP_TRUNK_ID,
                    sip_call_to=phone_number,
                    participant_identity=f"sip_{phone_number}",
                    wait_until_answered=True,  # ← Wait for user to answer
                )
            )

            logger.info("✅ Call answered by user. Agent will now greet.")

            # ✅ CRITICAL FIX: Generate the initial greeting
            # This is what makes the agent speak first
            logger.info("🎤 Generating initial greeting...")
            await session.generate_reply(
                instructions=config.INITIAL_GREETING
            )
            logger.info("✅ Greeting generated. Conversation started.")

        except Exception as e:
            logger.error(f"❌ Failed to place outbound call: {e}")
            logger.error(f"   Phone number: {phone_number}")
            logger.error(f"   SIP Trunk: {config.SIP_TRUNK_ID}")
            logger.error(f"   SIP Domain: {config.SIP_DOMAIN}")
            ctx.shutdown()
    else:
        # Inbound or test mode - just generate greeting
        logger.info("📱 No dial-out. Generating greeting for existing participant.")
        await session.generate_reply(
            instructions=config.fallback_greeting
        )
        logger.info("✅ Greeting generated.")


if __name__ == "__main__":
    agents.cli.run_app(
        agents.WorkerOptions(
            entrypoint_fnc=entrypoint,
            agent_name="outbound-caller",
        )
    )