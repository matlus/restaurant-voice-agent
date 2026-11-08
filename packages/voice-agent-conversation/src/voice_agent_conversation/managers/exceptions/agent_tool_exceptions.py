from typing import final, override

from voice_agent_conversation.managers.exceptions.voice_agent_conversation_exceptions import (
    ExceptionAction,
    LogEventBase,
    VoiceAgentConversationBusinessBaseException,
    VoiceAgentConversationTechnicalBaseException,
)


class LogEventAgentTool(LogEventBase):
    TOOL_CALL = "AgentToolCall"


@final
class AgentToolArgumentsInvalidException(VoiceAgentConversationBusinessBaseException):
    """The speech model called a tool with arguments that do not fit the tool's input. The model can call again correctly."""

    def __init__(self, tool_name: str, validation_problems: str) -> None:
        self.tool_name: str = tool_name
        super().__init__(
            message=f"The arguments for the tool '{tool_name}' are not valid: {validation_problems}",
            log_event=LogEventAgentTool.TOOL_CALL,
            contextual_data_by_name={"AgentTool.Name": tool_name},
        )

    @property
    @override
    def reason(self) -> str:
        return "The agent called a tool with invalid arguments"


@final
class AgentToolCallRepairsExhaustedException(VoiceAgentConversationTechnicalBaseException):
    """The speech model kept calling tools wrongly after being told how to correct each call, so the conversation ends."""

    def __init__(self, tool_name: str, repair_limit: int, last_problem: str) -> None:
        self.tool_name: str = tool_name
        super().__init__(
            message=(
                f"The agent called its tools wrongly more than {repair_limit} times in one conversation; "
                f"the last call, to '{tool_name}', failed with: {last_problem}"
            ),
            log_event=LogEventAgentTool.TOOL_CALL,
            contextual_data_by_name={"AgentTool.Name": tool_name, "AgentTool.RepairLimit": repair_limit},
        )

    @property
    @override
    def action(self) -> ExceptionAction:
        return ExceptionAction.DEVELOPER_ACTION_REQUIRED

    @property
    @override
    def reason(self) -> str:
        return "The agent kept calling its tools wrongly"
