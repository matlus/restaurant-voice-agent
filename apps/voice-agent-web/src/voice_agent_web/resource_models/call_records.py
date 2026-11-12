from dataclasses import dataclass

from voice_agent_conversation import AgentToolCallAnswered, CallLimit


@dataclass(frozen=True)
class CallRecord:
    """What the host saw of one call, kept for the summary logged when it ends. Nothing the guest said is kept."""

    voice_key: str | None
    conversation_id: str | None
    call_limit: CallLimit | None
    agent_tool_calls_answered: tuple[AgentToolCallAnswered, ...]
