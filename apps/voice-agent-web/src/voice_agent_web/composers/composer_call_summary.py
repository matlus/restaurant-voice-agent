from collections import Counter
from dataclasses import replace
from typing import Final

from voice_agent_conversation import AgentToolCallAnswered, CallLimitReached, ConversationEvent, ConversationStarted
from voice_agent_web.resource_models.call_records import CallRecord, CallSummaryResource


class ComposerCallSummary:
    """Builds the one structured event logged when a call ends: which conversation, how long, how it ended, and the
    agent's tool calls by name and outcome."""

    HUNG_UP_ENDING: Final[str] = "hung_up"
    FAILED_ENDING: Final[str] = "failed"
    CALL_LIMIT_ENDING_PREFIX: Final[str] = "call_limit:"

    @staticmethod
    def start_call_record(voice_key: str | None) -> CallRecord:
        return CallRecord(voice_key=voice_key, conversation_id=None, call_limit=None, agent_tool_calls_answered=())

    @staticmethod
    def record_event(call_record: CallRecord, conversation_event: ConversationEvent) -> CallRecord:
        match conversation_event:
            case ConversationStarted(conversation_id=conversation_id):
                return replace(call_record, conversation_id=conversation_id)
            case CallLimitReached(call_limit=call_limit):
                return replace(call_record, call_limit=call_limit)
            case AgentToolCallAnswered():
                return replace(call_record, agent_tool_calls_answered=(*call_record.agent_tool_calls_answered, conversation_event))
            case _:
                return call_record

    @classmethod
    def compose_call_summary(cls, call_record: CallRecord, call_seconds: float, *, call_failed: bool) -> CallSummaryResource:
        return {
            "event": "call_ended",
            "conversation_id": call_record.conversation_id,
            "voice_key": call_record.voice_key,
            "call_seconds": round(call_seconds, 1),
            "ending": cls._describe_ending(call_record, call_failed=call_failed),
            "agent_tool_calls": cls._count_agent_tool_calls(call_record.agent_tool_calls_answered),
        }

    @classmethod
    def _describe_ending(cls, call_record: CallRecord, *, call_failed: bool) -> str:
        if call_failed:
            return cls.FAILED_ENDING
        if call_record.call_limit is not None:
            return f"{cls.CALL_LIMIT_ENDING_PREFIX}{call_record.call_limit.value}"
        return cls.HUNG_UP_ENDING

    @staticmethod
    def _count_agent_tool_calls(agent_tool_calls_answered: tuple[AgentToolCallAnswered, ...]) -> dict[str, dict[str, int]]:
        count_by_outcome_by_tool_name: dict[str, Counter[str]] = {}
        agent_tool_call_answered: AgentToolCallAnswered
        for agent_tool_call_answered in agent_tool_calls_answered:
            count_by_outcome_by_tool_name.setdefault(agent_tool_call_answered.tool_name, Counter())[
                agent_tool_call_answered.agent_tool_call_outcome.value
            ] += 1
        return {tool_name: dict(count_by_outcome) for tool_name, count_by_outcome in count_by_outcome_by_tool_name.items()}
