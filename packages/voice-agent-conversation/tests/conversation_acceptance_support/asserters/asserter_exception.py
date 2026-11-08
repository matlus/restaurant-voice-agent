from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from conversation_acceptance_support.asserters.asserter_conversation import AsserterConversation
from conversation_acceptance_support.asserters.assertion_report import assert_no_mismatches
from conversation_acceptance_support.realtime_voice_service_scripted import CapturedRealtimeSession

from voice_agent_conversation import (
    ConversationRequestValidationException,
    ExceptionAction,
    LogEventBase,
    Severity,
    VoiceAgentConversationBaseException,
    VoiceNotOfferedException,
)

type ContextualDataValue = str | int | float | bool


@dataclass(frozen=True)
class ExpectedExceptionMetadata:
    """What every conversation exception declares about itself, arranged by the test."""

    http_status_code: int
    exception_action: ExceptionAction
    reason: str
    severity: Severity
    log_event: LogEventBase


@dataclass(frozen=True)
class ExpectedExceptionContent:
    """What one raised conversation exception must say and carry.

    Each message phrase must appear in the message, which may say more. Each contextual entry must be present with
    its value, and each absent name must be missing; the exception may carry other entries. Each absent phrase, such as
    a credential the scenario supplied, must appear nowhere in the message or in any contextual value.
    """

    message_phrases: Sequence[str]
    expected_exception_metadata: ExpectedExceptionMetadata
    contextual_data_by_name: Mapping[str, ContextualDataValue]
    absent_contextual_data_names: Sequence[str] = ()
    absent_phrases: Sequence[str] = ()


class AsserterException:
    """Compares a raised conversation exception, and what it left at the provider, with the test's expectations.

    Every obligation is evaluated and every mismatch is reported in one failure.
    """

    @staticmethod
    def assert_voice_not_offered_refusal_is_as_expected(
        *,
        expected_offered_voice_keys: Sequence[str],
        expected_exception_content: ExpectedExceptionContent,
        expected_provider_session_count: int,
        actual_voice_not_offered_exception: VoiceNotOfferedException,
        actual_captured_realtime_sessions: Sequence[CapturedRealtimeSession],
    ) -> None:
        mismatch_messages: list[str] = []
        if actual_voice_not_offered_exception.offered_voice_keys != list(expected_offered_voice_keys):
            mismatch_messages.append(
                f"Offered voices: expected {list(expected_offered_voice_keys)!r}; actual {actual_voice_not_offered_exception.offered_voice_keys!r}."
            )
        mismatch_messages.extend(AsserterException._find_exception_mismatches(expected_exception_content, actual_voice_not_offered_exception))
        mismatch_messages.extend(
            AsserterConversation.find_provider_session_mismatches(expected_provider_session_count, actual_captured_realtime_sessions)
        )
        assert_no_mismatches(
            mismatch_messages,
            failure_claim=(
                "VoiceNotOfferedException must name the offered voices, carry the refusal metadata and context, and leave the provider untouched "
                f"(actual message: {actual_voice_not_offered_exception.message!r})"
            ),
        )

    @staticmethod
    def assert_validation_refusal_is_as_expected(
        *,
        expected_validation_problem_count: int,
        expected_exception_content: ExpectedExceptionContent,
        expected_provider_session_count: int,
        actual_conversation_request_validation_exception: ConversationRequestValidationException,
        actual_captured_realtime_sessions: Sequence[CapturedRealtimeSession],
    ) -> None:
        mismatch_messages: list[str] = []
        if len(actual_conversation_request_validation_exception.validation_problems) != expected_validation_problem_count:
            mismatch_messages.append(
                f"Problem count: expected {expected_validation_problem_count}; "
                f"actual {len(actual_conversation_request_validation_exception.validation_problems)} "
                f"({actual_conversation_request_validation_exception.validation_problems!r})."
            )
        mismatch_messages.extend(
            AsserterException._find_exception_mismatches(expected_exception_content, actual_conversation_request_validation_exception)
        )
        mismatch_messages.extend(
            AsserterConversation.find_provider_session_mismatches(expected_provider_session_count, actual_captured_realtime_sessions)
        )
        assert_no_mismatches(
            mismatch_messages,
            failure_claim=(
                "ConversationRequestValidationException must list the expected problems, carry the refusal metadata and context, and leave "
                f"the provider untouched (actual problems: {actual_conversation_request_validation_exception.validation_problems!r})"
            ),
        )

    @staticmethod
    def assert_technical_failure_is_as_expected(
        *,
        expected_exception_content: ExpectedExceptionContent,
        expected_provider_session_count: int,
        actual_voice_agent_conversation_exception: VoiceAgentConversationBaseException,
        actual_captured_realtime_sessions: Sequence[CapturedRealtimeSession],
    ) -> None:
        """The exception's content, and every provider session it interrupted closed by the domain rather than left open."""
        mismatch_messages: list[str] = AsserterException._find_exception_mismatches(
            expected_exception_content, actual_voice_agent_conversation_exception
        )
        mismatch_messages.extend(
            AsserterConversation.find_provider_session_mismatches(expected_provider_session_count, actual_captured_realtime_sessions)
        )
        assert_no_mismatches(
            mismatch_messages,
            failure_claim=(
                f"{type(actual_voice_agent_conversation_exception).__name__} must carry the expected message phrases, metadata and context, "
                f"and leave no provider session open (actual message: {actual_voice_agent_conversation_exception.message!r})"
            ),
        )

    @staticmethod
    def _find_exception_mismatches(
        expected_exception_content: ExpectedExceptionContent, actual_voice_agent_conversation_exception: VoiceAgentConversationBaseException
    ) -> list[str]:
        mismatch_messages: list[str] = [
            f"Message is missing {expected_message_phrase!r}."
            for expected_message_phrase in expected_exception_content.message_phrases
            if expected_message_phrase not in actual_voice_agent_conversation_exception.message
        ]
        mismatch_messages.extend(
            AsserterException._find_disclosed_phrase_mismatches(expected_exception_content.absent_phrases, actual_voice_agent_conversation_exception)
        )
        mismatch_messages.extend(
            AsserterException._find_metadata_mismatches(
                expected_exception_content.expected_exception_metadata, actual_voice_agent_conversation_exception
            )
        )
        mismatch_messages.extend(
            AsserterException._find_contextual_data_mismatches(
                expected_exception_content.contextual_data_by_name,
                expected_exception_content.absent_contextual_data_names,
                actual_voice_agent_conversation_exception,
            )
        )
        return mismatch_messages

    @staticmethod
    def _find_disclosed_phrase_mismatches(
        expected_absent_phrases: Iterable[str], actual_voice_agent_conversation_exception: VoiceAgentConversationBaseException
    ) -> list[str]:
        mismatch_messages: list[str] = []
        expected_absent_phrase: str
        contextual_data_name: str
        contextual_data_value: ContextualDataValue
        for expected_absent_phrase in expected_absent_phrases:
            if expected_absent_phrase in actual_voice_agent_conversation_exception.message:
                mismatch_messages.append(f"Message discloses {expected_absent_phrase!r}, which must be absent.")
            for contextual_data_name, contextual_data_value in actual_voice_agent_conversation_exception.contextual_data_by_name.items():
                if expected_absent_phrase in str(contextual_data_value):
                    mismatch_messages.append(f"Context {contextual_data_name!r} discloses {expected_absent_phrase!r}, which must be absent.")
        return mismatch_messages

    @staticmethod
    def _find_metadata_mismatches(
        expected_exception_metadata: ExpectedExceptionMetadata, actual_voice_agent_conversation_exception: VoiceAgentConversationBaseException
    ) -> list[str]:
        mismatch_messages: list[str] = []
        if actual_voice_agent_conversation_exception.http_status_code != expected_exception_metadata.http_status_code:
            mismatch_messages.append(
                f"HTTP status: expected {expected_exception_metadata.http_status_code}; "
                f"actual {actual_voice_agent_conversation_exception.http_status_code}."
            )
        if actual_voice_agent_conversation_exception.action != expected_exception_metadata.exception_action:
            mismatch_messages.append(
                f"Action: expected {expected_exception_metadata.exception_action.value}; "
                f"actual {actual_voice_agent_conversation_exception.action.value}."
            )
        if actual_voice_agent_conversation_exception.reason != expected_exception_metadata.reason:
            mismatch_messages.append(
                f"Reason: expected {expected_exception_metadata.reason!r}; actual {actual_voice_agent_conversation_exception.reason!r}."
            )
        if actual_voice_agent_conversation_exception.severity != expected_exception_metadata.severity:
            mismatch_messages.append(
                f"Severity: expected {expected_exception_metadata.severity.name}; actual {actual_voice_agent_conversation_exception.severity.name}."
            )
        if actual_voice_agent_conversation_exception.log_event != expected_exception_metadata.log_event:
            mismatch_messages.append(
                f"Log event: expected {expected_exception_metadata.log_event.value}; "
                f"actual {actual_voice_agent_conversation_exception.log_event.value}."
            )
        return mismatch_messages

    @staticmethod
    def _find_contextual_data_mismatches(
        expected_contextual_data_by_name: Mapping[str, ContextualDataValue],
        expected_absent_contextual_data_names: Iterable[str],
        actual_voice_agent_conversation_exception: VoiceAgentConversationBaseException,
    ) -> list[str]:
        actual_contextual_data_by_name: dict[str, ContextualDataValue] = actual_voice_agent_conversation_exception.contextual_data_by_name
        mismatch_messages: list[str] = []
        contextual_data_name: str
        expected_contextual_data_value: ContextualDataValue
        for contextual_data_name, expected_contextual_data_value in expected_contextual_data_by_name.items():
            if actual_contextual_data_by_name.get(contextual_data_name) != expected_contextual_data_value:
                mismatch_messages.append(
                    f"Context {contextual_data_name!r}: expected {expected_contextual_data_value!r}; "
                    f"actual {actual_contextual_data_by_name.get(contextual_data_name)!r}."
                )
        mismatch_messages.extend(
            f"Context {absent_contextual_data_name!r}: expected absent; actual {actual_contextual_data_by_name[absent_contextual_data_name]!r}."
            for absent_contextual_data_name in expected_absent_contextual_data_names
            if absent_contextual_data_name in actual_contextual_data_by_name
        )
        return mismatch_messages
