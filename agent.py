import os
import certifi

# Fix for macOS SSL Certificate errors - MUST be before other imports
os.environ["SSL_CERT_FILE"] = certifi.where()

import logging
import json
from pathlib import Path
from dotenv import load_dotenv

from livekit import agents, api
from livekit.agents import AgentSession, Agent, RoomInputOptions

# Load environment variables - always from project root
load_dotenv(dotenv_path=Path(__file__).parent / ".env")

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

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("outbound-agent")

import config


def _build_tts(config_provider: str = None, config_voice: str = None):
    """Configure the Text-to-Speech provider based on env vars or dynamic config."""
    provider = (config_provider or os.getenv("TTS_PROVIDER", config.DEFAULT_TTS_PROVIDER)).lower()

    # If using Sarvam voice names, force Sarvam provider
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

        logger.info(f"Using Sarvam TTS | model={model} | voice={voice} | language={language}")

        if not os.getenv("SARVAM_API_KEY"):
            logger.error("SARVAM_API_KEY is missing. Sarvam TTS may fail.")

        return sarvam.TTS(model=model, speaker=voice, target_language_code=language)

    if provider == "deepgram":
        model = os.getenv("DEEPGRAM_TTS_MODEL", "aura-asteria-en")
        logger.info(f"Using Deepgram TTS | model={model}")
        return deepgram.TTS(model=model)

    # Default to OpenAI
    model = os.getenv("OPENAI_TTS_MODEL", "tts-1")
    voice = config_voice or os.getenv("OPENAI_TTS_VOICE", config.DEFAULT_TTS_VOICE)
    logger.info(f"Using OpenAI TTS | model={model} | voice={voice}")
    return openai.TTS(model=model, voice=voice)


def _build_llm(config_provider: str = None):
    """Configure the LLM provider based on config or env vars."""
    provider = (config_provider or os.getenv("LLM_PROVIDER", config.DEFAULT_LLM_PROVIDER)).lower()

    if provider == "groq":
        logger.info("Using Groq LLM")
        return openai.LLM(
            base_url="https://api.groq.com/openai/v1",
            api_key=os.getenv("GROQ_API_KEY"),
            model=os.getenv("GROQ_MODEL", config.GROQ_MODEL),
            temperature=float(os.getenv("GROQ_TEMPERATURE", str(config.GROQ_TEMPERATURE))),
        )

    logger.info("Using OpenAI LLM")
    return openai.LLM(model=config.DEFAULT_LLM_MODEL)


class TransferFunctions(llm.ToolContext):
    def __init__(self, ctx: agents.JobContext, phone_number: str = None):
        super().__init__(tools=[])
        self.ctx = ctx
        self.phone_number = phone_number

    @llm.function_tool(description="Look up user details by phone number.")
    async def lookup_user(self, phone: str):
        logger.info(f"Looking up user: {phone}")
        return "Lead found. Source: Divyasree WOW campaign. Status: New lead."

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

        logger.info(f"Transferring call to {destination}")

        participant_identity = None

        if self.phone_number:
            participant_identity = f"sip_{self.phone_number}"
        else:
            for p in self.ctx.room.remote_participants.values():
                participant_identity = p.identity
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
    def __init__(self, tools: list) -> None:
        super().__init__(
            instructions=config.SYSTEM_PROMPT,
            tools=tools,
        )


async def entrypoint(ctx: agents.JobContext):
    logger.info(f"Connecting to room: {ctx.room.name}")

    phone_number = None
    config_dict = {}

    try:
        if ctx.job.metadata:
            data = json.loads(ctx.job.metadata)
            phone_number = data.get("phone_number")
            config_dict = data
    except Exception:
        logger.warning("No valid JSON metadata found in job.")

    try:
        if ctx.room.metadata:
            data = json.loads(ctx.room.metadata)
            if data.get("phone_number"):
                phone_number = data.get("phone_number")
            config_dict.update(data)
    except Exception:
        logger.warning("No valid JSON metadata found in room.")

    fnc_ctx = TransferFunctions(ctx, phone_number)

    logger.info(
        f"Runtime STT | provider={config.STT_PROVIDER} | model={config.STT_MODEL} | language={config.STT_LANGUAGE}"
    )
    logger.info(
        f"Runtime LLM | provider={config_dict.get('model_provider') or os.getenv('LLM_PROVIDER', config.DEFAULT_LLM_PROVIDER)}"
    )
    logger.info(
        f"Runtime TTS | provider={config_dict.get('tts_provider') or os.getenv('TTS_PROVIDER', config.DEFAULT_TTS_PROVIDER)} | voice={config_dict.get('voice_id') or os.getenv('SARVAM_VOICE') or os.getenv('OPENAI_TTS_VOICE') or config.DEFAULT_TTS_VOICE}"
    )

    session = AgentSession(
        vad=silero.VAD.load(),
        stt=deepgram.STT(model=config.STT_MODEL, language=config.STT_LANGUAGE),
        llm=_build_llm(config_dict.get("model_provider")),
        tts=_build_tts(config_dict.get("tts_provider"), config_dict.get("voice_id")),
    )

    await session.start(
        room=ctx.room,
        agent=OutboundAssistant(tools=list(fnc_ctx.function_tools.values())),
        room_input_options=RoomInputOptions(
            noise_cancellation=noise_cancellation.BVCTelephony(),
            close_on_disconnect=True,
        ),
    )

    should_dial = False

    if phone_number:
        user_already_here = False
        for p in ctx.room.remote_participants.values():
            if f"sip_{phone_number}" in p.identity or "sip_" in p.identity:
                user_already_here = True
                break

        if not user_already_here:
            should_dial = True
            logger.info("User not in room. Agent will initiate dial-out.")
        else:
            logger.info("User already in room. Agent will only generate greeting.")

    if should_dial:
        logger.info(f"Initiating outbound SIP call to {phone_number}...")
        try:
            await ctx.api.sip.create_sip_participant(
                api.CreateSIPParticipantRequest(
                    room_name=ctx.room.name,
                    sip_trunk_id=config.SIP_TRUNK_ID,
                    sip_call_to=phone_number,
                    participant_identity=f"sip_{phone_number}",
                    wait_until_answered=True,
                )
            )

            logger.info("Call answered. Agent will now greet the user.")

            await session.generate_reply(
                instructions=config.INITIAL_GREETING
            )

        except Exception as e:
            logger.error(f"Failed to place outbound call: {e}")
            ctx.shutdown()
    else:
        logger.info("No dial-out needed. Generating fallback greeting.")
        await session.generate_reply(instructions=config.fallback_greeting)


if __name__ == "__main__":
    agents.cli.run_app(
        agents.WorkerOptions(
            entrypoint_fnc=entrypoint,
            agent_name="outbound-caller",
        )
    )