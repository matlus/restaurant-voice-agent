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
  rates and the voice), `guest_started_speaking` (stop playback at once), `agent_turn_finished`, and `error`
  (`title` and `detail`) before closing. Text frames from the browser are ignored.
- Close codes: `1000` when the call ends normally, `1008` when the request is refused (for example an unknown voice),
  `1013` when the voice service is temporarily unavailable, and `1011` for any other failure.
