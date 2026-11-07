from typing import Final, final, override

from openai import AsyncOpenAI, OpenAIError
from openai.resources.realtime.realtime import AsyncRealtimeConnection
from websockets.exceptions import WebSocketException

from voice_agent_conversation.managers.configuration_providers.settings_models.openai_realtime_settings import OpenAIRealtimeSettings
from voice_agent_conversation.managers.exceptions.realtime_voice_exceptions import LogEventRealtimeVoice
from voice_agent_conversation.managers.gateways.exception_translators.translator_openai_realtime_exceptions import (
    TranslatorOpenAIRealtimeExceptions,
)
from voice_agent_conversation.managers.gateways.realtime_voice_gateway_base import RealtimeVoiceGatewayBase, RealtimeVoiceSessionBase
from voice_agent_conversation.managers.gateways.realtime_voice_session_openai import RealtimeVoiceSessionOpenAI
from voice_agent_conversation.managers.models.conversation_models import VoiceSessionSettings


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
        realtime_voice_session_openai: RealtimeVoiceSessionOpenAI = RealtimeVoiceSessionOpenAI(connection)
        try:
            await realtime_voice_session_openai.configure(voice_session_settings)
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
