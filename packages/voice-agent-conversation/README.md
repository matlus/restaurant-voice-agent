# Voice Agent Conversation

Real-time voice conversations with the restaurant's agent over a speech-to-speech provider (OpenAI Realtime today).

The `DomainFacade` offers two capabilities:

- `get_voice_options()` lists the voices a guest can choose, from the bundled `catalog_data/voice_catalog.json`.
- `converse(request, guest_side_events)` holds one conversation. The guest's side sends `GuestSpeechChunk` audio and, after dropping agent speech it had not played because the guest talked over the agent, `AgentSpeechCutOff` with how much it dropped; the agent is then told where the guest stopped hearing it. It yields `ConversationStarted` (with the PCM sample rates), then the agent's speech chunks, `GuestStartedSpeaking` when the guest talks over the agent, and `AgentTurnFinished`.

Settings: `OPENAI_API_KEY` (required), `VOICE_AGENT_OPENAI_REALTIME_MODEL` (default `gpt-realtime-2.1`) and
`VOICE_AGENT_OPENAI_REALTIME_WEBSOCKET_BASE_URL` (optional, a `ws://` or `wss://` URL; unset means OpenAI's own address).

Tests never call OpenAI. The real gateway connects over a real WebSocket to a scripted Realtime service that the
test support runs on this machine, pointed at it through `VOICE_AGENT_OPENAI_REALTIME_WEBSOCKET_BASE_URL`.
