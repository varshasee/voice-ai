# AI Voice Agent – Divyasree "Whispers of the Wind"

## Overview

This project is an outbound AI voice agent designed to qualify potential buyers for Divyasree Developers’ premium villa plot project, *Whispers of the Wind (WOW)*.

The agent conducts a 2–3 minute conversational call to filter high-quality leads before passing them to a sales team.

---

## Assignment Objective

The goal was to design a voice agent that:

- Engages users in a natural conversation
- Qualifies leads across 4 key checkpoints
- Handles objections and edge cases
- Maintains a premium, non-intrusive tone
- Works across English and Hinglish conversations

---

## Project Context

- **Project:** Whispers of the Wind (WOW)
- **Location:** Nandi Valley (near Nandi Hills, North Bengaluru)
- **Product:** Premium villa plots (1200–3199 sq.ft.)
- **USP:**
  - 74% open spaces
  - 20,000 sq.ft. clubhouse
  - Eco-parks and scenic hill views
- **Pricing:** ₹92.4 lakh – ₹2.46 Cr
- **Target Audience:** HNIs, CXOs, NRIs
- **Possession:** December 2029

---

## Conversation Architecture

The agent follows a structured conversational flow:

### 1. Introduction
- Introduces itself as a Divyasree consultant
- Mentions project + location
- Asks for permission to continue

---

### 2. Qualification (4 Checkpoints)

- **Intent:** Self-use vs investment  
- **Geography:** Comfort with Nandi Hills / Devanahalli  
- **Budget:** Fit for ₹92.4 lakh+  
- **Timeline:** Comfort with 2029 delivery  

---

### 3. Pitch

Aspirational positioning:
- Private valley lifestyle
- Nature + community
- Investment upside

---

### 4. CTA

Requests a follow-up call with a property expert from the team.

---

## Key Features

- Natural conversational tone (premium, non-intrusive)
- Multilingual handling (English + Hinglish)
- Short, human-like responses (no long monologues)
- Smart flow control (does not repeat questions)
- Objection handling:
  - Budget mismatch
  - Location concerns
  - Busy / uninterested users
- Indian voice synthesis using Sarvam AI

---

## Tech Stack

- **LiveKit** – Voice infrastructure  
- **Groq (LLaMA 3)** – LLM  
- **Deepgram** – Speech-to-Text  
- **Sarvam AI** – Text-to-Speech (Indian voice)

## System Architecture

User Speech  
→ Deepgram (STT)  
→ Groq (LLM)  
→ Sarvam (TTS)  
→ Voice Output  

---

## Prompting Strategy

The system uses a structured prompt to:

- Maintain conversational flow
- Avoid hallucinations
- Ensure short, natural responses
- Control tone (premium, not salesy)

## Pronunciation Handling

Custom phonetic guidance was included for:

- Divyasree → Div-yaa-shree  
- Nandi → Nun-dhee  
- Lakh → Lak  
- Crore → Krohr  

Numbers are spoken naturally (e.g., “ninety two lakh”).

---

## Engineering Challenges & Solutions

### LLM Constraints
- **Challenge:** Free-tier Groq limits + weaker smaller models  
- **Solution:** Optimized prompt length and reduced temperature for stability  

---

### Voice Naturalness
- **Challenge:** Robotic / non-Indian tone  
- **Solution:** Tuned Sarvam TTS + Hinglish conversational prompts  

---

### Prompt Size vs Latency
- **Challenge:** Large prompts slowed inference  
- **Solution:** Used compact production prompt + detailed design prompt  

---

### Audio Testing Issues
- **Challenge:** Browser (Playground) audio inconsistencies  
- **Solution:** Validated using real outbound calls  

---

### Hallucination Control
- **Challenge:** LLM generating incorrect details  
- **Solution:** Strict prompt constraints + fallback to human expert  

---

## Note

The system is optimized for real-time performance while maintaining conversational quality and lead qualification accuracy.
