import asyncio
import base64
import contextlib
import json
import threading
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from http import HTTPStatus
from types import TracebackType
from typing import Final, Literal, NotRequired, Self, TypedDict, cast
from urllib.parse import parse_qs, urlsplit

from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Request, Response

SCRIPTED_GREETING_AUDIO: Final[bytes] = b"scripted greeting audio"
SCRIPTED_GREETING_RESPONSE_ID: Final[str] = "response_greeting"
SERVICE_HOST: Final[str] = "127.0.0.1"
SERVICE_START_TIMEOUT_SECONDS: Final[float] = 10.0
SERVICE_STOP_TIMEOUT_SECONDS: Final[float] = 10.0
CONNECTION_CLOSE_TIMEOUT_SECONDS: Final[float] = 1.0
PROVIDER_REFUSAL_CLOSE_CODE: Final[int] = 3000
ACTIVE_RESPONSE_ERROR_CODE: Final[str] = "conversation_already_has_active_response"
# The reply already under way when a reply request is refused, and an earlier reply whose end arrives late.
ACTIVE_REPLY_RESPONSE_ID: Final[str] = "response_active"
LATE_REPLY_RESPONSE_ID: Final[str] = "response_late"


# The subset of OpenAI Realtime server events this service sends, shaped as they travel on the wire.


class ProviderErrorDetailMessage(TypedDict):
    type: str
    code: str | None
    message: str
    # The client event that caused the error, when one did.
    event_id: NotRequired[str | None]


class ErrorEventMessage(TypedDict):
    type: Literal["error"]
    event_id: str
    error: ProviderErrorDetailMessage


class SpeechStartedEventMessage(TypedDict):
    type: Literal["input_audio_buffer.speech_started"]
    event_id: str
    audio_start_ms: int
    item_id: str


class SpeechStoppedEventMessage(TypedDict):
    type: Literal["input_audio_buffer.speech_stopped"]
    event_id: str
    audio_end_ms: int
    item_id: str


class OutputAudioDeltaEventMessage(TypedDict):
    type: Literal["response.output_audio.delta"]
    event_id: str
    response_id: str
    item_id: str
    output_index: int
    content_index: int
    delta: str


class ResponseStatusDetailsMessage(TypedDict):
    type: Literal["completed", "failed"]
    error: ProviderErrorDetailMessage | None


class ResponseMessage(TypedDict):
    id: str
    object: Literal["realtime.response"]
    status: Literal["completed", "failed"]
    status_details: ResponseStatusDetailsMessage | None
    # What the client attached when it asked for the reply.
    metadata: NotRequired[dict[str, str] | None]


class ResponseDoneEventMessage(TypedDict):
    type: Literal["response.done"]
    event_id: str
    response: ResponseMessage


class FunctionCallArgumentsDoneEventMessage(TypedDict):
    type: Literal["response.function_call_arguments.done"]
    event_id: str
    response_id: str
    item_id: str
    output_index: int
    call_id: str
    name: str
    arguments: str


class SessionEventMessage(TypedDict):
    type: Literal["session.created", "session.updated"]
    event_id: str
    session: dict[str, object]


type ScriptedServerEventMessage = (
    SpeechStartedEventMessage
    | SpeechStoppedEventMessage
    | ErrorEventMessage
    | ResponseDoneEventMessage
    | FunctionCallArgumentsDoneEventMessage
    | OutputAudioDeltaEventMessage
)
type ServerEventMessage = ScriptedServerEventMessage | SessionEventMessage


# The parts of the client events this service reads.


class AudioOutputSettingsMessage(TypedDict):
    voice: str


class AudioSettingsMessage(TypedDict):
    output: AudioOutputSettingsMessage


class FunctionToolMessage(TypedDict):
    type: Literal["function"]
    name: str
    description: str
    parameters: dict[str, object]


class SessionSettingsMessage(TypedDict):
    instructions: str
    audio: AudioSettingsMessage
    tools: list[FunctionToolMessage]


class SessionUpdateEventMessage(TypedDict):
    type: Literal["session.update"]
    session: SessionSettingsMessage


class InputAudioBufferAppendEventMessage(TypedDict):
    type: Literal["input_audio_buffer.append"]
    audio: str


class FunctionCallOutputItemMessage(TypedDict):
    type: Literal["function_call_output"]
    call_id: str
    output: str


class ConversationItemCreateEventMessage(TypedDict):
    type: Literal["conversation.item.create"]
    item: FunctionCallOutputItemMessage


class ConversationItemTruncateEventMessage(TypedDict):
    type: Literal["conversation.item.truncate"]
    item_id: str
    content_index: int
    audio_end_ms: int


def create_speech_started_event() -> SpeechStartedEventMessage:
    return {"type": "input_audio_buffer.speech_started", "event_id": "event_speech_started", "audio_start_ms": 0, "item_id": "item_guest"}


def create_speech_stopped_event() -> SpeechStoppedEventMessage:
    return {"type": "input_audio_buffer.speech_stopped", "event_id": "event_speech_stopped", "audio_end_ms": 0, "item_id": "item_guest"}


def create_agent_speech_event(item_id: str, pcm_audio: bytes) -> OutputAudioDeltaEventMessage:
    return {
        "type": "response.output_audio.delta",
        "event_id": f"event_{item_id}_audio",
        "response_id": f"response_{item_id}",
        "item_id": item_id,
        "output_index": 0,
        "content_index": 0,
        "delta": base64.b64encode(pcm_audio).decode("ascii"),
    }


def create_malformed_agent_speech_event() -> OutputAudioDeltaEventMessage:
    """A piece of agent speech whose audio is not valid base64, as a corrupted provider frame would carry."""
    malformed_output_audio_delta_event_message: OutputAudioDeltaEventMessage = create_agent_speech_event("item_malformed", b"")
    malformed_output_audio_delta_event_message["delta"] = "not base64 audio!"
    return malformed_output_audio_delta_event_message


def create_error_event(error_type: str, error_code: str | None, error_message: str, causing_client_event_id: str | None = None) -> ErrorEventMessage:
    return {
        "type": "error",
        "event_id": "event_error",
        "error": {"type": error_type, "code": error_code, "message": error_message, "event_id": causing_client_event_id},
    }


def create_response_done_event(response_id: str, reply_metadata: dict[str, str] | None) -> ResponseDoneEventMessage:
    return {
        "type": "response.done",
        "event_id": f"event_{response_id}_done",
        "response": {"id": response_id, "object": "realtime.response", "status": "completed", "status_details": None, "metadata": reply_metadata},
    }


def create_failed_response_event(error_type: str, error_code: str | None, error_message: str) -> ResponseDoneEventMessage:
    return {
        "type": "response.done",
        "event_id": "event_response_failed",
        "response": {
            "id": "response_failed",
            "object": "realtime.response",
            "status": "failed",
            "status_details": {"type": "failed", "error": {"type": error_type, "code": error_code, "message": error_message}},
        },
    }


def create_tool_call_events(call_id: str, tool_name: str, arguments_json: str) -> list[ScriptedServerEventMessage]:
    """A reply in which the model calls one tool and says nothing, as OpenAI sends it."""
    return [
        {
            "type": "response.function_call_arguments.done",
            "event_id": f"event_{call_id}_arguments",
            "response_id": f"response_{call_id}",
            "item_id": f"item_{call_id}",
            "output_index": 0,
            "call_id": call_id,
            "name": tool_name,
            "arguments": arguments_json,
        },
        {
            "type": "response.done",
            "event_id": f"event_{call_id}_done",
            "response": {"id": f"response_{call_id}", "object": "realtime.response", "status": "completed", "status_details": None},
        },
    ]


@dataclass(frozen=True)
class CapturedSessionSettings:
    """The session settings one session.update carried, as the service received them."""

    agent_instructions: str
    provider_voice_id: str
    tool_names: tuple[str, ...]


@dataclass(frozen=True)
class CapturedToolOutput:
    """One answer to a tool call, as the client sent it back."""

    call_id: str
    output: str


@dataclass(frozen=True)
class CapturedAgentSpeechTruncation:
    """One conversation.item.truncate the client sent: where the guest stopped hearing the agent's speech."""

    item_id: str
    content_index: int
    audio_end_ms: int


@dataclass
class CapturedRealtimeSession:
    """What one client connection did, as the service saw it on the wire. State only."""

    model: str | None
    session_settings: list[CapturedSessionSettings] = field(default_factory=list[CapturedSessionSettings])
    guest_audio: list[bytes] = field(default_factory=list[bytes])
    tool_outputs: list[CapturedToolOutput] = field(default_factory=list[CapturedToolOutput])
    agent_speech_truncations: list[CapturedAgentSpeechTruncation] = field(default_factory=list[CapturedAgentSpeechTruncation])
    agent_response_request_count: int = 0
    # The instructions each response.create carried for that reply alone, or None when it carried none.
    agent_response_instructions: list[str | None] = field(default_factory=list[str | None])
    was_closed_by_client: bool = False


class RealtimeVoiceServiceScripted:
    """A scripted stand-in for the OpenAI Realtime service, reached over a real WebSocket on this machine.

    The production gateway connects to it through its configured WebSocket base URL, so every line of the
    gateway, the session and its exception translator runs exactly as it does against OpenAI; only the far
    end of the wire is scripted. It confirms session settings, greets when asked for a response, answers
    each piece of guest audio with the scripted events, and captures every tool answer and speech truncation the client sends.
    It can also refuse the WebSocket handshake with an HTTP status, refuse an accepted connection by closing
    it the way OpenAI does for an invalid API key, or reject the session settings with a provider error event. It can
    refuse chosen reply requests, counted from one, as OpenAI does when a reply is already under way: it reports the
    refusal, naming the request it refused, and then the end of the reply that was under way. For other chosen reply
    requests it first reports the end of an earlier reply, as arrives when that end was still unread. Each reply it speaks
    carries back the metadata its request attached.

    It runs on its own thread and event loop, so asynchronous acceptance tests and the synchronous web
    test client can both use it. Read what it captured after it has stopped: stopping waits for every
    connection to finish, so nothing it received is still in flight.
    """

    def __init__(
        self,
        *,
        events_after_each_guest_audio: Sequence[ScriptedServerEventMessage] = (),
        session_update_error_event_message: ErrorEventMessage | None = None,
        handshake_refusal_status: HTTPStatus | None = None,
        connection_refusal_close_reason: str | None = None,
        refused_reply_request_numbers: Collection[int] = (),
        late_reply_completion_request_numbers: Collection[int] = (),
    ) -> None:
        self._events_after_each_guest_audio: tuple[ScriptedServerEventMessage, ...] = tuple(events_after_each_guest_audio)
        self._session_update_error_event_message: ErrorEventMessage | None = session_update_error_event_message
        self._handshake_refusal_status: HTTPStatus | None = handshake_refusal_status
        self._connection_refusal_close_reason: str | None = connection_refusal_close_reason
        self._refused_reply_request_numbers: frozenset[int] = frozenset(refused_reply_request_numbers)
        self._late_reply_completion_request_numbers: frozenset[int] = frozenset(late_reply_completion_request_numbers)
        self.captured_realtime_sessions: list[CapturedRealtimeSession] = []
        self.captured_handshake_count: int = 0
        self._port: int | None = None
        self._is_ready: threading.Event = threading.Event()
        self._service_thread: threading.Thread | None = None
        self._service_loop: asyncio.AbstractEventLoop | None = None
        self._stop_requested: asyncio.Event | None = None

    @property
    def websocket_base_url(self) -> str:
        if self._port is None:
            raise RuntimeError("The scripted Realtime service has not started.")
        return f"ws://{SERVICE_HOST}:{self._port}/v1"

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None) -> None:
        self.stop()

    async def __aenter__(self) -> Self:
        await asyncio.to_thread(self.start)
        return self

    async def __aexit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None) -> None:
        await asyncio.to_thread(self.stop)

    def start(self) -> None:
        self._service_thread = threading.Thread(target=asyncio.run, args=(self._serve(),), name="realtime-voice-service-scripted", daemon=True)
        self._service_thread.start()
        if not self._is_ready.wait(SERVICE_START_TIMEOUT_SECONDS) or self._port is None:
            raise RuntimeError("The scripted Realtime service did not start listening.")

    def stop(self) -> None:
        if self._service_loop is not None and self._stop_requested is not None:
            self._service_loop.call_soon_threadsafe(self._stop_requested.set)
        if self._service_thread is not None:
            self._service_thread.join(SERVICE_STOP_TIMEOUT_SECONDS)
            # What it captured is read only after it stops, so a thread still running would hand a test half the story.
            if self._service_thread.is_alive():
                raise RuntimeError("The scripted Realtime service did not stop in time.")

    async def _serve(self) -> None:
        self._service_loop = asyncio.get_running_loop()
        self._stop_requested = asyncio.Event()
        try:
            async with serve(
                self._hold_realtime_session,
                SERVICE_HOST,
                0,
                process_request=self._answer_handshake,
                close_timeout=CONNECTION_CLOSE_TIMEOUT_SECONDS,
            ) as server:
                self._port = next(iter(server.sockets)).getsockname()[1]
                self._is_ready.set()
                await self._stop_requested.wait()
        finally:
            self._is_ready.set()

    def _answer_handshake(self, server_connection: ServerConnection, request: Request) -> Response | None:
        self.captured_handshake_count += 1
        if self._handshake_refusal_status is None:
            return None
        return server_connection.respond(self._handshake_refusal_status, f"{self._handshake_refusal_status.phrase}\n")

    async def _hold_realtime_session(self, server_connection: ServerConnection) -> None:
        if self._connection_refusal_close_reason is not None:
            await server_connection.close(PROVIDER_REFUSAL_CLOSE_CODE, self._connection_refusal_close_reason)
            return
        captured_realtime_session: CapturedRealtimeSession = CapturedRealtimeSession(model=self._read_model(server_connection.request))
        self.captured_realtime_sessions.append(captured_realtime_session)
        try:
            await self._send_event(server_connection, {"type": "session.created", "event_id": "event_session_created", "session": {}})
            client_message: str | bytes
            async for client_message in server_connection:
                # A reply can fail once the client has closed; the events it sent before closing are still captured.
                with contextlib.suppress(ConnectionClosed):
                    await self._answer_client_event(server_connection, captured_realtime_session, json.loads(client_message))
        except ConnectionClosed:
            pass
        captured_realtime_session.was_closed_by_client = server_connection.protocol.close_rcvd_then_sent is True

    async def _answer_client_event(
        self, server_connection: ServerConnection, captured_realtime_session: CapturedRealtimeSession, client_event: Mapping[str, object]
    ) -> None:
        match client_event.get("type"):
            case "session.update":
                await self._answer_session_update(
                    server_connection, captured_realtime_session.session_settings, cast(SessionUpdateEventMessage, client_event)
                )
            case "response.create":
                captured_realtime_session.agent_response_request_count += 1
                response_settings: Mapping[str, object] = cast(Mapping[str, object], client_event.get("response") or {})
                captured_realtime_session.agent_response_instructions.append(cast(str | None, response_settings.get("instructions")))
                if captured_realtime_session.agent_response_request_count in self._refused_reply_request_numbers:
                    await self._refuse_reply_request(server_connection, cast(str | None, client_event.get("event_id")))
                    return
                if captured_realtime_session.agent_response_request_count in self._late_reply_completion_request_numbers:
                    await self._send_event(server_connection, create_response_done_event(LATE_REPLY_RESPONSE_ID, None))
                await self._speak_greeting(server_connection, cast(dict[str, str] | None, response_settings.get("metadata")))
            case "input_audio_buffer.append":
                input_audio_buffer_append_event_message: InputAudioBufferAppendEventMessage = cast(InputAudioBufferAppendEventMessage, client_event)
                captured_realtime_session.guest_audio.append(base64.b64decode(input_audio_buffer_append_event_message["audio"]))
                scripted_server_event_message: ScriptedServerEventMessage
                for scripted_server_event_message in self._events_after_each_guest_audio:
                    await self._send_event(server_connection, scripted_server_event_message)
            case "conversation.item.create":
                conversation_item_create_event_message: ConversationItemCreateEventMessage = cast(ConversationItemCreateEventMessage, client_event)
                function_call_output_item_message: FunctionCallOutputItemMessage = conversation_item_create_event_message["item"]
                captured_realtime_session.tool_outputs.append(
                    CapturedToolOutput(call_id=function_call_output_item_message["call_id"], output=function_call_output_item_message["output"])
                )
            case "conversation.item.truncate":
                conversation_item_truncate_event_message: ConversationItemTruncateEventMessage = cast(
                    ConversationItemTruncateEventMessage, client_event
                )
                captured_realtime_session.agent_speech_truncations.append(
                    CapturedAgentSpeechTruncation(
                        item_id=conversation_item_truncate_event_message["item_id"],
                        content_index=conversation_item_truncate_event_message["content_index"],
                        audio_end_ms=conversation_item_truncate_event_message["audio_end_ms"],
                    )
                )
            case _:
                pass

    async def _answer_session_update(
        self,
        server_connection: ServerConnection,
        captured_session_settings: list[CapturedSessionSettings],
        session_update_event_message: SessionUpdateEventMessage,
    ) -> None:
        session_settings_message: SessionSettingsMessage = session_update_event_message["session"]
        captured_session_settings.append(
            CapturedSessionSettings(
                agent_instructions=session_settings_message["instructions"],
                provider_voice_id=session_settings_message["audio"]["output"]["voice"],
                tool_names=tuple(function_tool_message["name"] for function_tool_message in session_settings_message["tools"]),
            )
        )
        if self._session_update_error_event_message is not None:
            await self._send_event(server_connection, self._session_update_error_event_message)
            return
        await self._send_event(
            server_connection,
            {"type": "session.updated", "event_id": "event_session_updated", "session": cast(dict[str, object], session_settings_message)},
        )

    @classmethod
    async def _refuse_reply_request(cls, server_connection: ServerConnection, refused_client_event_id: str | None) -> None:
        await cls._send_event(
            server_connection,
            create_error_event(
                "invalid_request_error",
                ACTIVE_RESPONSE_ERROR_CODE,
                "Conversation already has an active response in progress.",
                refused_client_event_id,
            ),
        )
        await cls._send_event(server_connection, create_response_done_event(ACTIVE_REPLY_RESPONSE_ID, None))

    @classmethod
    async def _speak_greeting(cls, server_connection: ServerConnection, reply_metadata: dict[str, str] | None) -> None:
        await cls._send_event(
            server_connection,
            {
                "type": "response.output_audio.delta",
                "event_id": "event_greeting_audio",
                "response_id": SCRIPTED_GREETING_RESPONSE_ID,
                "item_id": "item_greeting",
                "output_index": 0,
                "content_index": 0,
                "delta": base64.b64encode(SCRIPTED_GREETING_AUDIO).decode("ascii"),
            },
        )
        await cls._send_event(server_connection, create_response_done_event(SCRIPTED_GREETING_RESPONSE_ID, reply_metadata))

    @staticmethod
    async def _send_event(server_connection: ServerConnection, server_event_message: ServerEventMessage) -> None:
        await server_connection.send(json.dumps(server_event_message))

    @staticmethod
    def _read_model(request: Request | None) -> str | None:
        if request is None:
            return None
        model_values: list[str] = parse_qs(urlsplit(request.path).query).get("model", [])
        return model_values[0] if model_values else None
