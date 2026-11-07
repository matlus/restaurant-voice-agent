from typing import final, override

from voice_agent_conversation.managers.exceptions.voice_agent_conversation_exceptions import (
    ContextualDataDict,
    ExceptionAction,
    LogEventBase,
    VoiceAgentConversationTechnicalBaseException,
)


class LogEventConfiguration(LogEventBase):
    OPENAI_REALTIME_SETTINGS_RETRIEVAL = "OpenAIRealtimeSettingsRetrieval"


@final
class ConfigurationSettingException(VoiceAgentConversationTechnicalBaseException):
    def __init__(self, message: str, log_event: LogEventBase, contextual_data_by_name: ContextualDataDict | None = None) -> None:
        super().__init__(message=message, log_event=log_event, contextual_data_by_name=contextual_data_by_name)

    @property
    @override
    def action(self) -> ExceptionAction:
        return ExceptionAction.INFRA_ACTION_REQUIRED

    @property
    @override
    def reason(self) -> str:
        return "Configuration settings are not set up correctly"
