from typing import Final

from websockets.exceptions import ConnectionClosed, InvalidStatus

from voice_agent_conversation.managers.exceptions.realtime_voice_exceptions import (
    RealtimeVoiceProviderAccessDeniedException,
    RealtimeVoiceProviderErrorException,
    RealtimeVoiceProviderUnavailableException,
)
from voice_agent_conversation.managers.exceptions.voice_agent_conversation_exceptions import (
    ContextualDataDict,
    LogEventBase,
    VoiceAgentConversationTechnicalBaseException,
)


class TranslatorOpenAIRealtimeExceptions:
    """Turns OpenAI Realtime failures into the domain's speech provider exceptions, in one place.

    Connection trouble may pass if a new conversation is started. Refused credentials need the key
    fixed. Anything else the provider reports means our request was wrong and a developer must look.
    """

    ACCESS_DENIED_HTTP_STATUS_CODES: Final[frozenset[int]] = frozenset({401, 403})
    TRANSIENT_HTTP_STATUS_CODES: Final[frozenset[int]] = frozenset({408, 429, 500, 502, 503, 504})
    ACCESS_DENIED_ERROR_CODES: Final[frozenset[str]] = frozenset({"invalid_api_key", "insufficient_quota"})
    SERVER_ERROR_TYPE: Final[str] = "server_error"
    # OpenAI refuses a connection it has already accepted, such as one with an invalid API key, by closing
    # it with an application close code (3000-4999) whose reason reads "<error type>.<error code>".
    PROVIDER_CLOSE_CODES: Final[range] = range(3000, 5000)
    OPERATION_CONTEXT_KEY: Final[str] = "RealtimeVoice.Operation"
    PROVIDER_ERROR_CODE_CONTEXT_KEY: Final[str] = "RealtimeVoice.ProviderErrorCode"
    PROVIDER_NAME: Final[str] = "OpenAI Realtime"

    @classmethod
    def translate_connection_failure(
        cls, provider_error: Exception, operation_description: str, log_event: LogEventBase
    ) -> VoiceAgentConversationTechnicalBaseException:
        provider_close_reason: str | None = cls._get_provider_close_reason(provider_error)
        if provider_close_reason is not None:
            return cls._translate_provider_refusal(provider_close_reason, operation_description, log_event)
        contextual_data_by_name: ContextualDataDict = cls._build_connection_context(provider_error, operation_description)
        if isinstance(provider_error, InvalidStatus):
            return cls._translate_invalid_status(provider_error, operation_description, log_event, contextual_data_by_name)
        return cls._create_unavailable_exception(provider_error, operation_description, log_event, contextual_data_by_name)

    @classmethod
    def translate_reported_error(
        cls, error_type: str, error_code: str | None, error_message: str, operation_description: str, log_event: LogEventBase
    ) -> VoiceAgentConversationTechnicalBaseException:
        contextual_data_by_name: ContextualDataDict = {
            cls.OPERATION_CONTEXT_KEY: operation_description,
            "RealtimeVoice.ProviderErrorType": error_type,
        }
        if error_code is not None:
            contextual_data_by_name[cls.PROVIDER_ERROR_CODE_CONTEXT_KEY] = error_code
        if error_code in cls.ACCESS_DENIED_ERROR_CODES:
            return RealtimeVoiceProviderAccessDeniedException(
                message=f"{cls.PROVIDER_NAME} refused the account while {operation_description}: {error_message}",
                log_event=log_event,
                contextual_data_by_name=contextual_data_by_name,
            )
        if error_type == cls.SERVER_ERROR_TYPE:
            return RealtimeVoiceProviderUnavailableException(
                message=f"{cls.PROVIDER_NAME} failed while {operation_description}: {error_message}",
                log_event=log_event,
                contextual_data_by_name=contextual_data_by_name,
            )
        return RealtimeVoiceProviderErrorException(
            message=f"{cls.PROVIDER_NAME} reported an error while {operation_description}: {error_message}",
            log_event=log_event,
            contextual_data_by_name=contextual_data_by_name,
        )

    @classmethod
    def _get_provider_close_reason(cls, provider_error: Exception) -> str | None:
        """The close reason when the provider itself closed the connection to refuse it, or None for any other failure."""
        if isinstance(provider_error, ConnectionClosed) and provider_error.rcvd is not None and provider_error.rcvd.code in cls.PROVIDER_CLOSE_CODES:
            return provider_error.rcvd.reason
        return None

    @classmethod
    def _translate_provider_refusal(
        cls, provider_close_reason: str, operation_description: str, log_event: LogEventBase
    ) -> VoiceAgentConversationTechnicalBaseException:
        error_type: str
        error_code: str
        error_type, _, error_code = provider_close_reason.partition(".")
        return cls.translate_reported_error(error_type, error_code or None, provider_close_reason, operation_description, log_event)

    @classmethod
    def _build_connection_context(cls, provider_error: Exception, operation_description: str) -> ContextualDataDict:
        return {
            cls.OPERATION_CONTEXT_KEY: operation_description,
            "RealtimeVoice.ErrorType": type(provider_error).__name__,
            "RealtimeVoice.Error": str(provider_error),
        }

    @classmethod
    def _translate_invalid_status(
        cls, provider_error: InvalidStatus, operation_description: str, log_event: LogEventBase, contextual_data_by_name: ContextualDataDict
    ) -> VoiceAgentConversationTechnicalBaseException:
        http_status_code: int = provider_error.response.status_code
        contextual_data_by_name["RealtimeVoice.HttpStatusCode"] = http_status_code
        if http_status_code in cls.ACCESS_DENIED_HTTP_STATUS_CODES:
            return RealtimeVoiceProviderAccessDeniedException(
                message=f"{cls.PROVIDER_NAME} refused the API key while {operation_description} (HTTP {http_status_code}).",
                log_event=log_event,
                contextual_data_by_name=contextual_data_by_name,
            )
        if http_status_code not in cls.TRANSIENT_HTTP_STATUS_CODES:
            return RealtimeVoiceProviderErrorException(
                message=f"{cls.PROVIDER_NAME} rejected the request while {operation_description} (HTTP {http_status_code}).",
                log_event=log_event,
                contextual_data_by_name=contextual_data_by_name,
            )
        return cls._create_unavailable_exception(provider_error, operation_description, log_event, contextual_data_by_name)

    @classmethod
    def _create_unavailable_exception(
        cls, provider_error: Exception, operation_description: str, log_event: LogEventBase, contextual_data_by_name: ContextualDataDict
    ) -> RealtimeVoiceProviderUnavailableException:
        return RealtimeVoiceProviderUnavailableException(
            message=f"Could not reach {cls.PROVIDER_NAME} while {operation_description}: {provider_error}",
            log_event=log_event,
            contextual_data_by_name=contextual_data_by_name,
        )
