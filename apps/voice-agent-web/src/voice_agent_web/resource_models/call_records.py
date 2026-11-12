from dataclasses import dataclass
from typing import Literal, TypedDict

from voice_agent_conversation import AgentToolCallAnswered, CallLimit


@dataclass(frozen=True)
class CallRecord:
    """What the host saw of one call, kept for the summary logged when it ends. Nothing the guest said is kept."""

    voice_key: str | None
    conversation_id: str | None
    call_limit: CallLimit | None
    agent_tool_calls_answered: tuple[AgentToolCallAnswered, ...]


class CallSummaryResource(TypedDict):
    """The structured event logged once when a call ends."""

    event: Literal["call_ended"]
    conversation_id: str | None
    voice_key: str | None
    call_seconds: float
    ending: str
    agent_tool_calls: dict[str, dict[str, int]]
