import asyncio
import base64
import binascii
from collections.abc import AsyncIterator
from typing import Final, NoReturn, final, override

from openai import AsyncOpenAI, OpenAIError
from openai.resources.realtime.realtime import AsyncRealtimeConnection
from openai.types.realtime import RealtimeResponseStatus, RealtimeServerEvent
from openai.types.realtime.realtime_function_tool_param import RealtimeFunctionToolParam
from openai.types.realtime.realtime_response_status import Error as RealtimeResponseStatusError
from openai.types.realtime.realtime_session_create_request_param import RealtimeSessionCreateRequestParam
from websockets.exceptions import WebSocketException

from voice_agent_conversation.managers.configuration_providers.settings_models.openai_realtime_settings import OpenAIRealtimeSettings
from voice_agent_conversation.managers.exceptions.realtime_voice_exceptions import LogEventRealtimeVoice
from voice_agent_conversation.managers.exceptions.voice_agent_conversation_exceptions import LogEventBase
from voice_agent_conversation.managers.gateways.exception_translators.translator_openai_realtime_exceptions import (
    TranslatorOpenAIRealtimeExceptions,
)
from voice_agent_conversation.managers.gateways.realtime_voice_gateway_base import RealtimeVoiceGatewayBase, RealtimeVoiceSessionBase
from voice_agent_conversation.managers.models.conversation_models import (
    AgentSpeechPart,
    AgentSpeechReceived,
    AgentToolCallRequested,
    AgentToolDefinition,
    AgentTurnFinished,
    ConversationAudioFormat,
    GuestStartedSpeaking,
    VoiceSessionEvent,
    VoiceSessionSettings,
)

type _ProviderFailure = OpenAIError | WebSocketException | OSError


@final
class RealtimeVoiceGatewayOpenAI(RealtimeVoiceGatewayBase):
    """Opens conversations with the OpenAI Realtime API over WebSocket.

    A dropped conversation is not reconnected: the provider would forget everything said so far,
    so the conversation ends and the guest can start a new one.
    """

    CONNECT_OPERATION_DESCRIPTION_TEMPLATE: Final[str] = "connecting to model '{model}'"
    CLOSE_OPERATION_DESCRIPTION: Final[str] = "closing the provider client"

    def __init__(self, openai_realtime_settings: OpenAIRealtimeSettings) -> None:
        self._model: str = openai_realtime_settings.model
        self._client: AsyncOpenAI | None = AsyncOpenAI(
            api_key=openai_realtime_settings.api_key, websocket_base_url=openai_realtime_settings.websocket_base_url
        )

    @override
    async def open_session(self, voice_session_settings: VoiceSessionSettings) -> RealtimeVoiceSessionBase:
        client: AsyncOpenAI = self._get_open_client()
        try:
            connection: AsyncRealtimeConnection = await client.realtime.connect(model=self._model).enter()
        except (OpenAIError, WebSocketException, OSError) as provider_error:
            raise TranslatorOpenAIRealtimeExceptions.translate_connection_failure(
                provider_error, self._describe_connect_operation(), LogEventRealtimeVoice.SESSION_OPEN
            ) from provider_error
        realtime_voice_session_openai: _RealtimeVoiceSessionOpenAI = _RealtimeVoiceSessionOpenAI(connection, voice_session_settings)
        try:
            await realtime_voice_session_openai.configure()
        except BaseException:
            await realtime_voice_session_openai.close()
            raise
        return realtime_voice_session_openai

    @override
    async def close(self) -> None:
        if self._client is None:
            return
        client: AsyncOpenAI = self._client
        # Forgotten before closing, so a second close() does nothing even when this one fails.
        self._client = None
        try:
            await client.close()
        except (OpenAIError, WebSocketException, OSError) as provider_error:
            raise TranslatorOpenAIRealtimeExceptions.translate_connection_failure(
                provider_error, self.CLOSE_OPERATION_DESCRIPTION, LogEventRealtimeVoice.CLIENT_CLOSE
            ) from provider_error

    def _get_open_client(self) -> AsyncOpenAI:
        if self._client is None:
            raise TranslatorOpenAIRealtimeExceptions.translate_connection_failure(
                ConnectionError("the gateway is already closed"), self._describe_connect_operation(), LogEventRealtimeVoice.SESSION_OPEN
            )
        return self._client

    def _describe_connect_operation(self) -> str:
        return self.CONNECT_OPERATION_DESCRIPTION_TEMPLATE.format(model=self._model)


@final
class _RealtimeVoiceSessionOpenAI(RealtimeVoiceSessionBase):
    """One OpenAI Realtime conversation over a WebSocket the gateway has already connected. Only the gateway above
    creates it; the manager drives it through RealtimeVoiceSessionBase.

    The provider emits many more event types than a voice-only conversation needs, such as transcripts
    and item bookkeeping. Those are ignored by design, not by omission.

    It keeps no record of the conversation beyond its connection: whoever drives it decides when to ask for the next
    reply and how much of the agent's speech the guest heard.
    """

    # The provider accepts only 24 kHz PCM, so the constant keeps its literal type for the SDK's typed session.
    SAMPLE_RATE_HZ: Final = 24_000
    # The guest's turn ends after this much silence. Semantic turn detection waited 4 to 7 seconds after a guest stopped
    # before the agent spoke, measured live; silence detection at half a second answers in about 1 to 2.
    TURN_END_SILENCE_MILLISECONDS: Final[int] = 500
    SESSION_CONFIRMATION_TIMEOUT_SECONDS: Final[float] = 10.0
    CONFIGURE_OPERATION_DESCRIPTION: Final[str] = "configuring the session"
    CONVERSE_OPERATION_DESCRIPTION: Final[str] = "conversing"

    def __init__(self, connection: AsyncRealtimeConnection, voice_session_settings: VoiceSessionSettings) -> None:
        self._connection: AsyncRealtimeConnection | None = connection
        self._voice_session_settings: VoiceSessionSettings = voice_session_settings

    @property
    @override
    def conversation_audio_format(self) -> ConversationAudioFormat:
        return ConversationAudioFormat(guest_audio_sample_rate_hz=self.SAMPLE_RATE_HZ, agent_audio_sample_rate_hz=self.SAMPLE_RATE_HZ)

    async def configure(self) -> None:
        """Sends the session settings and returns once the provider has accepted them; a rejected setting raises here."""
        connection: AsyncRealtimeConnection = self._get_open_connection()
        try:
            await connection.session.update(session=self._build_session_configuration(self._voice_session_settings))
            async with asyncio.timeout(self.SESSION_CONFIRMATION_TIMEOUT_SECONDS):
                await self._wait_for_session_confirmation(connection)
        except TimeoutError as timeout_error:
            self._raise_connection_failure(
                timeout_error, "waiting for the provider to confirm the session settings", LogEventRealtimeVoice.SESSION_CONFIGURATION
            )
        except (OpenAIError, WebSocketException, OSError) as provider_error:
            self._raise_connection_failure(provider_error, self.CONFIGURE_OPERATION_DESCRIPTION, LogEventRealtimeVoice.SESSION_CONFIGURATION)

    @override
    async def send_guest_audio(self, pcm_audio: bytes) -> None:
        connection: AsyncRealtimeConnection = self._get_open_connection()
        try:
            await connection.input_audio_buffer.append(audio=base64.b64encode(pcm_audio).decode("ascii"))
        except (OpenAIError, WebSocketException, OSError) as provider_error:
            self._raise_connection_failure(provider_error, "sending guest audio", LogEventRealtimeVoice.GUEST_AUDIO_SEND)

    @override
    async def request_greeting(self, greeting_instructions: str) -> None:
        # Instructions given with one reply replace the session's for that reply, so the standing ones go with them.
        connection: AsyncRealtimeConnection = self._get_open_connection()
        try:
            await connection.response.create(
                response={"instructions": f"{self._voice_session_settings.agent_instructions}\n\n{greeting_instructions}"}
            )
        except (OpenAIError, WebSocketException, OSError) as provider_error:
            self._raise_connection_failure(provider_error, "requesting the greeting", LogEventRealtimeVoice.AGENT_RESPONSE_REQUEST)

    @override
    async def request_next_reply(self) -> None:
        connection: AsyncRealtimeConnection = self._get_open_connection()
        try:
            await connection.response.create()
        except (OpenAIError, WebSocketException, OSError) as provider_error:
            self._raise_connection_failure(provider_error, "requesting an agent response", LogEventRealtimeVoice.AGENT_RESPONSE_REQUEST)

    @override
    async def cut_off_agent_speech(self, agent_speech_part: AgentSpeechPart, heard_milliseconds: int) -> None:
        connection: AsyncRealtimeConnection = self._get_open_connection()
        try:
            await connection.conversation.item.truncate(
                item_id=agent_speech_part.reply_item_id, content_index=agent_speech_part.content_index, audio_end_ms=heard_milliseconds
            )
        except (OpenAIError, WebSocketException, OSError) as provider_error:
            self._raise_connection_failure(
                provider_error, "cutting off the agent speech the guest did not hear", LogEventRealtimeVoice.AGENT_SPEECH_CUT_OFF
            )

    @override
    async def send_tool_result(self, call_id: str, tool_output: str) -> None:
        connection: AsyncRealtimeConnection = self._get_open_connection()
        try:
            await connection.conversation.item.create(item={"type": "function_call_output", "call_id": call_id, "output": tool_output})
        except (OpenAIError, WebSocketException, OSError) as provider_error:
            self._raise_connection_failure(provider_error, "answering a tool call", LogEventRealtimeVoice.TOOL_RESULT_SEND)

    @override
    async def receive_events(self) -> AsyncIterator[VoiceSessionEvent]:
        connection: AsyncRealtimeConnection = self._get_open_connection()
        server_event: RealtimeServerEvent
        try:
            async for server_event in connection:
                voice_session_event: VoiceSessionEvent | None = self._to_voice_session_event(server_event)
                if voice_session_event is not None:
                    yield voice_session_event
        except (OpenAIError, WebSocketException, OSError) as provider_error:
            # close() makes the SDK raise out of this iteration. After close() that failure is the shutdown we asked for, not a fault.
            if self._connection is not None:
                self._raise_connection_failure(provider_error, "receiving conversation events", LogEventRealtimeVoice.EVENT_RECEIPT)

    @override
    async def close(self) -> None:
        if self._connection is None:
            return
        connection: AsyncRealtimeConnection = self._connection
        # Forgotten before closing, so a second close() does nothing even when this one fails.
        self._connection = None
        try:
            await connection.close()
        except (OpenAIError, WebSocketException, OSError) as provider_error:
            self._raise_connection_failure(provider_error, "closing the session", LogEventRealtimeVoice.SESSION_CLOSE)

    def _get_open_connection(self) -> AsyncRealtimeConnection:
        if self._connection is None:
            raise TranslatorOpenAIRealtimeExceptions.translate_connection_failure(
                ConnectionError("the session is already closed"), "using the session", LogEventRealtimeVoice.EVENT_RECEIPT
            )
        return self._connection

    @classmethod
    def _build_session_configuration(cls, voice_session_settings: VoiceSessionSettings) -> RealtimeSessionCreateRequestParam:
        return {
            "type": "realtime",
            "instructions": voice_session_settings.agent_instructions,
            "output_modalities": ["audio"],
            "audio": {
                "input": {
                    "format": {"type": "audio/pcm", "rate": cls.SAMPLE_RATE_HZ},
                    "turn_detection": {
                        "type": "server_vad",
                        "silence_duration_ms": cls.TURN_END_SILENCE_MILLISECONDS,
                        "create_response": True,
                        "interrupt_response": True,
                    },
                },
                "output": {
                    "format": {"type": "audio/pcm", "rate": cls.SAMPLE_RATE_HZ},
                    "voice": voice_session_settings.provider_voice_id,
                },
            },
            "tools": [cls._to_function_tool(agent_tool_definition) for agent_tool_definition in voice_session_settings.agent_tool_definitions],
            "tool_choice": "auto",
        }

    @staticmethod
    def _to_function_tool(agent_tool_definition: AgentToolDefinition) -> RealtimeFunctionToolParam:
        return {
            "type": "function",
            "name": agent_tool_definition.name,
            "description": agent_tool_definition.description,
            "parameters": agent_tool_definition.parameters_schema,
        }

    @classmethod
    async def _wait_for_session_confirmation(cls, connection: AsyncRealtimeConnection) -> None:
        # Events before the confirmation, such as session.created, are dropped: no audio has been sent or requested yet,
        # so none of them is something the conversation must hear.
        while True:
            server_event: RealtimeServerEvent = await connection.recv()
            if server_event.type == "session.updated":
                return
            if server_event.type == "error":
                raise TranslatorOpenAIRealtimeExceptions.translate_reported_error(
                    error_type=server_event.error.type,
                    error_code=server_event.error.code,
                    error_message=server_event.error.message,
                    operation_description=cls.CONFIGURE_OPERATION_DESCRIPTION,
                    log_event=LogEventRealtimeVoice.SESSION_CONFIGURATION,
                )

    @classmethod
    def _to_voice_session_event(cls, server_event: RealtimeServerEvent) -> VoiceSessionEvent | None:
        match server_event.type:
            case "response.output_audio.delta":
                return AgentSpeechReceived(
                    pcm_audio=cls._decode_agent_speech(server_event.delta),
                    agent_speech_part=AgentSpeechPart(reply_item_id=server_event.item_id, content_index=server_event.content_index),
                )
            case "input_audio_buffer.speech_started":
                return GuestStartedSpeaking()
            case "response.function_call_arguments.done":
                return AgentToolCallRequested(call_id=server_event.call_id, tool_name=server_event.name, arguments_json=server_event.arguments)
            case "response.done":
                if server_event.response.status == "failed":
                    status_details: RealtimeResponseStatus | None = server_event.response.status_details
                    failure: RealtimeResponseStatusError | None = status_details.error if status_details is not None else None
                    raise TranslatorOpenAIRealtimeExceptions.translate_reported_error(
                        error_type=(failure.type if failure is not None else None) or "response_failed",
                        error_code=failure.code if failure is not None else None,
                        error_message=(failure.message if failure is not None else None) or "The agent's response failed.",
                        operation_description=cls.CONVERSE_OPERATION_DESCRIPTION,
                        log_event=LogEventRealtimeVoice.EVENT_RECEIPT,
                    )
                return AgentTurnFinished()
            case "error":
                raise TranslatorOpenAIRealtimeExceptions.translate_reported_error(
                    error_type=server_event.error.type,
                    error_code=server_event.error.code,
                    error_message=server_event.error.message,
                    operation_description=cls.CONVERSE_OPERATION_DESCRIPTION,
                    log_event=LogEventRealtimeVoice.EVENT_RECEIPT,
                )
            case _:
                return None

    @classmethod
    def _decode_agent_speech(cls, base64_audio: str) -> bytes:
        try:
            return base64.b64decode(base64_audio, validate=True)
        except binascii.Error as decode_error:
            raise TranslatorOpenAIRealtimeExceptions.translate_reported_error(
                error_type="malformed_audio",
                error_code=None,
                error_message="The provider sent agent speech that is not valid base64 audio.",
                operation_description=cls.CONVERSE_OPERATION_DESCRIPTION,
                log_event=LogEventRealtimeVoice.EVENT_RECEIPT,
            ) from decode_error

    @staticmethod
    def _raise_connection_failure(provider_error: _ProviderFailure, operation_description: str, log_event: LogEventBase) -> NoReturn:
        raise TranslatorOpenAIRealtimeExceptions.translate_connection_failure(provider_error, operation_description, log_event) from provider_error
