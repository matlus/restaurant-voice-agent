from collections.abc import Sequence
from typing import final, override

from voice_agent_conversation.managers.exceptions.voice_agent_conversation_exceptions import (
    ContextualDataDict,
    ExceptionAction,
    LogEventBase,
    VoiceAgentConversationBusinessBaseException,
    VoiceAgentConversationTechnicalBaseException,
)


class LogEventConversation(LogEventBase):
    CONVERSATION_START = "ConversationStart"
    VOICE_CATALOG_READ = "VoiceCatalogRead"


@final
class ConversationRequestValidationException(VoiceAgentConversationBusinessBaseException):
    """The conversation request is incomplete or malformed. Every problem found is listed, not just the first."""

    def __init__(self, validation_problems: Sequence[str], log_event: LogEventBase) -> None:
        self.validation_problems: list[str] = list(validation_problems)
        super().__init__(
            message="The conversation cannot start: " + " ".join(self.validation_problems),
            log_event=log_event,
            contextual_data_by_name={"Conversation.ValidationProblemCount": len(self.validation_problems)},
        )

    @property
    @override
    def reason(self) -> str:
        return "The conversation request is not valid"


@final
class VoiceNotOfferedException(VoiceAgentConversationBusinessBaseException):
    """The requested voice is not in the catalog. The message lists the voices that are."""

    def __init__(self, requested_voice_key: str, offered_voice_keys: Sequence[str], log_event: LogEventBase) -> None:
        self.requested_voice_key: str = requested_voice_key
        self.offered_voice_keys: list[str] = list(offered_voice_keys)
        super().__init__(
            message=f"The voice '{requested_voice_key}' is not offered. Choose one of: {', '.join(self.offered_voice_keys)}.",
            log_event=log_event,
            contextual_data_by_name={"Conversation.RequestedVoiceKey": requested_voice_key},
        )

    @property
    @override
    def http_status_code(self) -> int:
        return 404

    @property
    @override
    def reason(self) -> str:
        return "The requested voice is not offered"


@final
class VoiceCatalogInvalidException(VoiceAgentConversationTechnicalBaseException):
    """The voice catalog bundled with the package cannot be read. A developer must correct the file."""

    def __init__(self, message: str, log_event: LogEventBase, contextual_data_by_name: ContextualDataDict | None = None) -> None:
        super().__init__(message=message, log_event=log_event, contextual_data_by_name=contextual_data_by_name)

    @property
    @override
    def action(self) -> ExceptionAction:
        return ExceptionAction.DEVELOPER_ACTION_REQUIRED

    @property
    @override
    def reason(self) -> str:
        return "The bundled voice catalog is invalid"
