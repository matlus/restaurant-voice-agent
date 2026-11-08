from collections.abc import Iterable, Sequence

from conversation_acceptance_support.asserters.assertion_report import assert_no_mismatches
from conversation_acceptance_support.realtime_voice_service_scripted import CapturedRealtimeSession, CapturedSessionSettings

from voice_agent_conversation import ConversationEvent


class AsserterConversation:
    """Compares what a conversation yielded, and what reached the scripted Realtime service, with the test's expectations."""

    @staticmethod
    def assert_conversation_events_are_as_expected(
        *, expected_conversation_events: Sequence[ConversationEvent], actual_conversation_events: Sequence[ConversationEvent]
    ) -> None:
        assert_no_mismatches(
            AsserterConversation._find_conversation_event_mismatches(expected_conversation_events, actual_conversation_events),
            failure_claim="The conversation must yield the expected events in order",
        )

    @staticmethod
    def assert_call_is_as_expected(
        *,
        expected_conversation_events: Sequence[ConversationEvent],
        expected_guest_audio: Sequence[bytes],
        expected_agent_response_request_count: int,
        actual_conversation_events: Sequence[ConversationEvent],
        actual_captured_realtime_sessions: Sequence[CapturedRealtimeSession],
    ) -> None:
        """The events the host heard, and the one provider session that carried the guest's audio and the greeting request."""
        mismatch_messages: list[str] = AsserterConversation._find_conversation_event_mismatches(
            expected_conversation_events, actual_conversation_events
        )
        if len(actual_captured_realtime_sessions) != 1:
            mismatch_messages.append(f"Provider sessions: expected 1; actual {len(actual_captured_realtime_sessions)}.")
        else:
            actual_captured_realtime_session: CapturedRealtimeSession = actual_captured_realtime_sessions[0]
            if actual_captured_realtime_session.guest_audio != list(expected_guest_audio):
                mismatch_messages.append(
                    f"Guest audio: expected {list(expected_guest_audio)!r}; actual {actual_captured_realtime_session.guest_audio!r}."
                )
            if actual_captured_realtime_session.agent_response_request_count != expected_agent_response_request_count:
                mismatch_messages.append(
                    f"Greeting requests: expected {expected_agent_response_request_count}; "
                    f"actual {actual_captured_realtime_session.agent_response_request_count}."
                )
        assert_no_mismatches(mismatch_messages, failure_claim="The call must yield the expected events and reach the provider as expected")

    @staticmethod
    def assert_agent_briefing_is_as_expected(
        *,
        expected_provider_voice_id: str,
        expected_instruction_phrases: Iterable[str],
        actual_captured_realtime_sessions: Sequence[CapturedRealtimeSession],
    ) -> None:
        mismatch_messages: list[str] = []
        actual_session_settings: list[CapturedSessionSettings] = [
            captured_session_settings
            for actual_captured_realtime_session in actual_captured_realtime_sessions
            for captured_session_settings in actual_captured_realtime_session.session_settings
        ]
        if len(actual_session_settings) != 1:
            mismatch_messages.append(f"Session settings sent: expected 1; actual {len(actual_session_settings)}.")
        else:
            actual_captured_session_settings: CapturedSessionSettings = actual_session_settings[0]
            if actual_captured_session_settings.provider_voice_id != expected_provider_voice_id:
                mismatch_messages.append(
                    f"Provider voice: expected {expected_provider_voice_id!r}; actual {actual_captured_session_settings.provider_voice_id!r}."
                )
            mismatch_messages.extend(
                f"Instructions are missing {expected_instruction_phrase!r}. Actual: {actual_captured_session_settings.agent_instructions!r}."
                for expected_instruction_phrase in expected_instruction_phrases
                if expected_instruction_phrase not in actual_captured_session_settings.agent_instructions
            )
        assert_no_mismatches(mismatch_messages, failure_claim="The agent must be briefed once, in the chosen voice, with the expected facts")

    @staticmethod
    def assert_provider_sessions_were_closed_by_the_domain(
        *, expected_provider_session_count: int, actual_captured_realtime_sessions: Sequence[CapturedRealtimeSession]
    ) -> None:
        assert_no_mismatches(
            AsserterConversation.find_provider_session_mismatches(expected_provider_session_count, actual_captured_realtime_sessions),
            failure_claim="Every provider session must be closed by the domain, not left for the provider to drop",
        )

    @staticmethod
    def find_provider_session_mismatches(
        expected_provider_session_count: int, actual_captured_realtime_sessions: Sequence[CapturedRealtimeSession]
    ) -> list[str]:
        mismatch_messages: list[str] = []
        if len(actual_captured_realtime_sessions) != expected_provider_session_count:
            mismatch_messages.append(
                f"Provider sessions: expected {expected_provider_session_count}; actual {len(actual_captured_realtime_sessions)}."
            )
        session_position: int
        actual_captured_realtime_session: CapturedRealtimeSession
        for session_position, actual_captured_realtime_session in enumerate(actual_captured_realtime_sessions):
            if not actual_captured_realtime_session.was_closed_by_client:
                mismatch_messages.append(
                    f"Provider session {session_position}: expected closed by the domain; actual still open when the service stopped."
                )
        return mismatch_messages

    @staticmethod
    def _find_conversation_event_mismatches(
        expected_conversation_events: Sequence[ConversationEvent], actual_conversation_events: Sequence[ConversationEvent]
    ) -> list[str]:
        mismatch_messages: list[str] = []
        if len(actual_conversation_events) != len(expected_conversation_events):
            mismatch_messages.append(f"Event count: expected {len(expected_conversation_events)}; actual {len(actual_conversation_events)}.")
        event_position: int
        for event_position in range(max(len(expected_conversation_events), len(actual_conversation_events))):
            expected_conversation_event: ConversationEvent | None = (
                expected_conversation_events[event_position] if event_position < len(expected_conversation_events) else None
            )
            actual_conversation_event: ConversationEvent | None = (
                actual_conversation_events[event_position] if event_position < len(actual_conversation_events) else None
            )
            if actual_conversation_event != expected_conversation_event:
                mismatch_messages.append(
                    f"Event {event_position}: expected {expected_conversation_event or 'no event'!r}; "
                    f"actual {actual_conversation_event or 'no event'!r}."
                )
        return mismatch_messages
