# Voice Agent Web

The web host for the Ember & Sprout voice agent. It serves a page with one microphone button and a voice choice,
and relays audio between the browser and the conversation domain over a WebSocket.

## Run it

Put `OPENAI_API_KEY` in the gitignored `.env` at the repository root (see `.env.example`), then from the root:

```bash
uv run --all-packages voice_agent_web
```

Open http://127.0.0.1:8000, choose a voice and press the button. The browser asks for the microphone once.

## Wire format

- `GET /voices` returns `{"voices": [{"voice_key", "presented_gender", "description"}]}`.
- `WS /conversation?voice=<voice_key>`: the browser sends binary frames of mono 16-bit PCM at the guest sample rate.
  The server sends binary frames of the agent's PCM and JSON text frames: `conversation_started` (with both sample
  rates), `guest_started_speaking` (stop playback at once), `agent_turn_finished`, `call_limit_reached` (with a
  `detail` to show, after the agent's goodbye and before a normal close), and `error` before closing. The page
  answers `guest_started_speaking` with `{"type": "agent_speech_cut_off", "unplayed_milliseconds": n}` when it dropped
  speech it had not played, so the agent does not think the caller heard it; other text frames are ignored.

A `/conversation` handshake whose `Origin` is neither this host nor in `VOICE_AGENT_WEB_ALLOWED_ORIGINS` is refused.
No more than `VOICE_AGENT_MAXIMUM_CONCURRENT_CALLS` calls (default 10) run in one process; the host enforces this
before the domain sees the call. A caller beyond it gets an `error` frame and a `1013` close.
