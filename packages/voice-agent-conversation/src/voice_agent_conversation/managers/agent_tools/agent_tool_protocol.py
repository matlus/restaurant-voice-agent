from typing import Protocol

from voice_agent_conversation.managers.models.conversation_models import AgentToolDefinition


class AgentToolProtocol(Protocol):
    """What the toolbox needs from every tool, whatever its input and result types."""

    @property
    def name(self) -> str: ...

    def get_tool_definition(self) -> AgentToolDefinition: ...

    async def invoke(self, arguments_json: str) -> str: ...
