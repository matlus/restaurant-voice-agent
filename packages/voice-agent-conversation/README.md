# Voice Agent Conversation

Real-time voice conversations with the restaurant's agent over a speech-to-speech provider (OpenAI Realtime today).

The `DomainFacade` offers two capabilities:

- `get_voice_options()` lists the voices a guest can choose, from the bundled `catalog_data/voice_catalog.json`.
- `converse(request, guest_side_events)` holds one conversation. The guest's side sends `GuestSpeechChunk` audio and, after dropping agent speech it had not played because the guest talked over the agent, `AgentSpeechCutOff` with how much it dropped; the agent is then told where the guest stopped hearing it. It yields `ConversationStarted` (with the PCM sample rates), then the agent's speech chunks, `GuestStartedSpeaking` when the guest talks over the agent, and `AgentTurnFinished`. It also yields `SpeechProviderErrorTolerated` when the provider reports an error known to leave the call running; the host logs it and does not pass it to the guest. `GuestFacingConversationEvent` names the other four. Any other provider error ends the call. A session that reaches the provider's time limit ends with `RealtimeVoiceSessionExpiredException`, a business exception whose message tells the guest to call again.

Calls are bounded: a call ends with a spoken goodbye and `CallLimitReached` at its maximum length or after the guest has been silent too long; beyond the concurrent-call limit `converse` raises `ConversationCapacityReachedException`; guest audio pieces over 200 ms, or arriving faster than real time beyond a one-second burst, are dropped.

Settings: `OPENAI_API_KEY` (required), `VOICE_AGENT_OPENAI_REALTIME_MODEL` (default `gpt-realtime-2.1`) and
`VOICE_AGENT_OPENAI_REALTIME_WEBSOCKET_BASE_URL` (optional, a `ws://` or `wss://` URL; unset means OpenAI's own address), and the call limits `VOICE_AGENT_MAXIMUM_CALL_SECONDS` (default 900), `VOICE_AGENT_MAXIMUM_SILENCE_SECONDS` (default 120) and `VOICE_AGENT_MAXIMUM_CONCURRENT_CALLS` (default 10).

Tests never call OpenAI. The real gateway connects over a real WebSocket to a scripted Realtime service that the
test support runs on this machine, pointed at it through `VOICE_AGENT_OPENAI_REALTIME_WEBSOCKET_BASE_URL`.
