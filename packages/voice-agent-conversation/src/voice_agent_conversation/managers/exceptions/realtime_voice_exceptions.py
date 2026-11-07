from typing import final, override

from voice_agent_conversation.managers.exceptions.voice_agent_conversation_exceptions import (
    ContextualDataDict,
    ExceptionAction,
    LogEventBase,
    VoiceAgentConversationTechnicalBaseException,
)


class LogEventRealtimeVoice(LogEventBase):
    SESSION_OPEN = "RealtimeVoiceSessionOpen"
    SESSION_CONFIGURATION = "RealtimeVoiceSessionConfiguration"
    GUEST_AUDIO_SEND = "RealtimeVoiceGuestAudioSend"
    AGENT_RESPONSE_REQUEST = "RealtimeVoiceAgentResponseRequest"
    EVENT_RECEIPT = "RealtimeVoiceEventReceipt"
    SESSION_CLOSE = "RealtimeVoiceSessionClose"
    CLIENT_CLOSE = "RealtimeVoiceClientClose"


@final
class RealtimeVoiceProviderUnavailableException(VoiceAgentConversationTechnicalBaseException):
    """The speech provider could not be reached or dropped the connection. Starting a new conversation may succeed."""

    def __init__(self, message: str, log_event: LogEventBase, contextual_data_by_name: ContextualDataDict | None = None) -> None:
        super().__init__(message=message, log_event=log_event, contextual_data_by_name=contextual_data_by_name)

    @property
    @override
    def http_status_code(self) -> int:
        return 503

    @property
    @override
    def action(self) -> ExceptionAction:
        return ExceptionAction.RETRY_ACTION_NEEDED

    @property
    @override
    def reason(self) -> str:
        return "The voice service is temporarily unavailable"


@final
class RealtimeVoiceProviderAccessDeniedException(VoiceAgentConversationTechnicalBaseException):
    """The speech provider refused the credentials. The API key setting must be corrected."""

    def __init__(self, message: str, log_event: LogEventBase, contextual_data_by_name: ContextualDataDict | None = None) -> None:
        super().__init__(message=message, log_event=log_event, contextual_data_by_name=contextual_data_by_name)

    @property
    @override
    def action(self) -> ExceptionAction:
        return ExceptionAction.INFRA_ACTION_REQUIRED

    @property
    @override
    def reason(self) -> str:
        return "The voice service refused access"


@final
class RealtimeVoiceProviderErrorException(VoiceAgentConversationTechnicalBaseException):
    """The speech provider reported an error in the conversation, such as a rejected session setting or a failed response."""

    def __init__(self, message: str, log_event: LogEventBase, contextual_data_by_name: ContextualDataDict | None = None) -> None:
        super().__init__(message=message, log_event=log_event, contextual_data_by_name=contextual_data_by_name)

    @property
    @override
    def http_status_code(self) -> int:
        return 502

    @property
    @override
    def action(self) -> ExceptionAction:
        return ExceptionAction.DEVELOPER_ACTION_REQUIRED

    @property
    @override
    def reason(self) -> str:
        return "The voice service reported an error"
