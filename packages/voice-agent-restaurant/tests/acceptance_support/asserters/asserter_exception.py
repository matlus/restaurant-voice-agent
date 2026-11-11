from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import time

from voice_agent_restaurant import (
    DishLookupValidationException,
    DishNotFoundException,
    ExceptionAction,
    LogEventBase,
    MenuSearchValidationException,
    NoTableAvailableException,
    ReservationPolicyRefusedException,
    ReservationRequestValidationException,
    Severity,
    VoiceAgentRestaurantBaseException,
)

type ValidationException = ReservationRequestValidationException | MenuSearchValidationException | DishLookupValidationException
type ContextualDataValue = str | int | float | bool


@dataclass(frozen=True)
class ExpectedExceptionMetadata:
    """What every restaurant exception declares about itself, arranged by the test."""

    http_status_code: int
    exception_action: ExceptionAction
    reason: str
    severity: Severity
    log_event: LogEventBase


@dataclass(frozen=True)
class ExpectedExceptionContent:
    """What one raised restaurant exception must say and carry.

    Each message phrase must appear in the message, which may say more, and no withheld phrase, such as a confirmation
    code the caller must not hear, may appear in it. Each contextual entry must be present with its value, and each
    present name must be present with any value; the exception may carry other entries.
    """

    message_phrases: Sequence[str]
    exception_metadata: ExpectedExceptionMetadata
    contextual_data_by_name: Mapping[str, ContextualDataValue]
    present_contextual_data_names: Sequence[str] = ()
    withheld_message_phrases: Sequence[str] = ()


class AsserterException:
    """Compares a raised exception with the test's expectations and reports every mismatch in one failure."""

    @staticmethod
    def assert_message_and_metadata_are_as_expected(
        *, expected_exception_content: ExpectedExceptionContent, actual_voice_agent_restaurant_exception: VoiceAgentRestaurantBaseException
    ) -> None:
        AsserterException._assert_no_mismatches(
            AsserterException._find_exception_content_mismatches(expected_exception_content, actual_voice_agent_restaurant_exception),
            failure_claim=(
                f"{type(actual_voice_agent_restaurant_exception).__name__} must carry the expected message phrases, HTTP status, action, "
                f"reason, severity and context (actual message: {actual_voice_agent_restaurant_exception.message!r})"
            ),
        )

    @staticmethod
    def assert_validation_problems_are_as_expected(
        *,
        expected_problem_phrases: Sequence[str],
        expected_exception_metadata: ExpectedExceptionMetadata,
        expected_contextual_data_by_name: Mapping[str, ContextualDataValue],
        actual_validation_exception: ValidationException,
    ) -> None:
        AsserterException._assert_problems_are_as_expected(
            ExpectedExceptionContent(
                message_phrases=expected_problem_phrases,
                exception_metadata=expected_exception_metadata,
                contextual_data_by_name=expected_contextual_data_by_name,
            ),
            actual_validation_exception.validation_problems,
            actual_validation_exception,
        )

    @staticmethod
    def assert_policy_problems_are_as_expected(
        *,
        expected_problem_phrases: Sequence[str],
        expected_exception_metadata: ExpectedExceptionMetadata,
        expected_contextual_data_by_name: Mapping[str, ContextualDataValue],
        actual_reservation_policy_refused_exception: ReservationPolicyRefusedException,
    ) -> None:
        AsserterException._assert_problems_are_as_expected(
            ExpectedExceptionContent(
                message_phrases=expected_problem_phrases,
                exception_metadata=expected_exception_metadata,
                contextual_data_by_name=expected_contextual_data_by_name,
            ),
            actual_reservation_policy_refused_exception.policy_problems,
            actual_reservation_policy_refused_exception,
        )

    @staticmethod
    def assert_no_table_refusal_is_as_expected(
        *,
        expected_alternative_times: Sequence[time],
        expected_exception_content: ExpectedExceptionContent,
        actual_no_table_available_exception: NoTableAvailableException,
    ) -> None:
        assertion_failures: list[str] = []
        if actual_no_table_available_exception.alternative_times != list(expected_alternative_times):
            assertion_failures.append(
                f"Alternative times: expected {list(expected_alternative_times)!r}; actual {actual_no_table_available_exception.alternative_times!r}."
            )
        assertion_failures.extend(
            AsserterException._find_exception_content_mismatches(expected_exception_content, actual_no_table_available_exception)
        )
        AsserterException._assert_no_mismatches(
            assertion_failures,
            failure_claim=(
                f"{type(actual_no_table_available_exception).__name__} must refuse with the expected alternative times, message, refusal metadata "
                f"and context (actual message: {actual_no_table_available_exception.message!r})"
            ),
        )

    @staticmethod
    def assert_dish_not_found_refusal_is_as_expected(
        *,
        expected_close_match_names: Sequence[str],
        expected_exception_content: ExpectedExceptionContent,
        actual_dish_not_found_exception: DishNotFoundException,
    ) -> None:
        assertion_failures: list[str] = []
        if actual_dish_not_found_exception.close_match_names != list(expected_close_match_names):
            assertion_failures.append(
                f"Close match names: expected {list(expected_close_match_names)!r}; actual {actual_dish_not_found_exception.close_match_names!r}."
            )
        assertion_failures.extend(AsserterException._find_message_mismatches(expected_close_match_names, actual_dish_not_found_exception.message))
        assertion_failures.extend(AsserterException._find_exception_content_mismatches(expected_exception_content, actual_dish_not_found_exception))
        AsserterException._assert_no_mismatches(
            assertion_failures,
            failure_claim=(
                f"{type(actual_dish_not_found_exception).__name__} must refuse with the expected close match names, message, refusal "
                f"metadata and context (actual message: {actual_dish_not_found_exception.message!r})"
            ),
        )

    @staticmethod
    def _find_exception_content_mismatches(
        expected_exception_content: ExpectedExceptionContent, actual_voice_agent_restaurant_exception: VoiceAgentRestaurantBaseException
    ) -> list[str]:
        assertion_failures: list[str] = AsserterException._find_message_mismatches(
            expected_exception_content.message_phrases, actual_voice_agent_restaurant_exception.message
        )
        assertion_failures.extend(
            AsserterException._find_withheld_message_phrases(
                expected_exception_content.withheld_message_phrases, actual_voice_agent_restaurant_exception.message
            )
        )
        assertion_failures.extend(
            AsserterException._find_metadata_mismatches(expected_exception_content.exception_metadata, actual_voice_agent_restaurant_exception)
        )
        assertion_failures.extend(
            AsserterException._find_contextual_data_mismatches(
                expected_exception_content.contextual_data_by_name,
                expected_exception_content.present_contextual_data_names,
                actual_voice_agent_restaurant_exception,
            )
        )
        return assertion_failures

    @staticmethod
    def _find_message_mismatches(expected_message_phrases: Iterable[str], actual_exception_message: str) -> list[str]:
        return [
            f"Message is missing {expected_message_phrase!r}. Actual message: {actual_exception_message!r}."
            for expected_message_phrase in expected_message_phrases
            if expected_message_phrase not in actual_exception_message
        ]

    @staticmethod
    def _find_withheld_message_phrases(expected_withheld_message_phrases: Iterable[str], actual_exception_message: str) -> list[str]:
        return [
            f"Message reveals withheld {expected_withheld_message_phrase!r}. Actual message: {actual_exception_message!r}."
            for expected_withheld_message_phrase in expected_withheld_message_phrases
            if expected_withheld_message_phrase in actual_exception_message
        ]

    @staticmethod
    def _find_metadata_mismatches(
        expected_exception_metadata: ExpectedExceptionMetadata, actual_voice_agent_restaurant_exception: VoiceAgentRestaurantBaseException
    ) -> list[str]:
        assertion_failures: list[str] = []
        if actual_voice_agent_restaurant_exception.http_status_code != expected_exception_metadata.http_status_code:
            assertion_failures.append(
                f"HTTP status: expected {expected_exception_metadata.http_status_code}; "
                f"actual {actual_voice_agent_restaurant_exception.http_status_code}."
            )
        if actual_voice_agent_restaurant_exception.action != expected_exception_metadata.exception_action:
            assertion_failures.append(
                f"Action: expected {expected_exception_metadata.exception_action.value}; "
                f"actual {actual_voice_agent_restaurant_exception.action.value}."
            )
        if actual_voice_agent_restaurant_exception.reason != expected_exception_metadata.reason:
            assertion_failures.append(
                f"Reason: expected {expected_exception_metadata.reason!r}; actual {actual_voice_agent_restaurant_exception.reason!r}."
            )
        if actual_voice_agent_restaurant_exception.severity != expected_exception_metadata.severity:
            assertion_failures.append(
                f"Severity: expected {expected_exception_metadata.severity.name}; actual {actual_voice_agent_restaurant_exception.severity.name}."
            )
        if actual_voice_agent_restaurant_exception.log_event != expected_exception_metadata.log_event:
            assertion_failures.append(
                f"Log event: expected {expected_exception_metadata.log_event.value}; "
                f"actual {actual_voice_agent_restaurant_exception.log_event.value}."
            )
        return assertion_failures

    @staticmethod
    def _find_contextual_data_mismatches(
        expected_contextual_data_by_name: Mapping[str, ContextualDataValue],
        expected_present_contextual_data_names: Iterable[str],
        actual_voice_agent_restaurant_exception: VoiceAgentRestaurantBaseException,
    ) -> list[str]:
        actual_contextual_data_by_name: dict[str, ContextualDataValue] = actual_voice_agent_restaurant_exception.contextual_data_by_name
        assertion_failures: list[str] = []
        contextual_data_name: str
        expected_contextual_data_value: ContextualDataValue
        for contextual_data_name, expected_contextual_data_value in expected_contextual_data_by_name.items():
            # Types are compared too: False == 0 and 4 == 4.0, but a flag is not a count.
            actual_contextual_data_value: ContextualDataValue | None = actual_contextual_data_by_name.get(contextual_data_name)
            if (type(actual_contextual_data_value), actual_contextual_data_value) != (
                type(expected_contextual_data_value),
                expected_contextual_data_value,
            ):
                assertion_failures.append(
                    f"Context {contextual_data_name!r}: expected {expected_contextual_data_value!r}; actual {actual_contextual_data_value!r}."
                )
        assertion_failures.extend(
            f"Context {present_contextual_data_name!r}: expected present; actual absent."
            for present_contextual_data_name in expected_present_contextual_data_names
            if present_contextual_data_name not in actual_contextual_data_by_name
        )
        return assertion_failures

    @staticmethod
    def _assert_problems_are_as_expected(
        expected_exception_content: ExpectedExceptionContent,
        actual_problems: Sequence[str],
        actual_voice_agent_restaurant_exception: VoiceAgentRestaurantBaseException,
    ) -> None:
        assertion_failures: list[str] = []
        if len(actual_problems) != len(expected_exception_content.message_phrases):
            assertion_failures.append(
                f"Problem count: expected {len(expected_exception_content.message_phrases)}; actual {len(actual_problems)} ({actual_problems!r})."
            )
        assertion_failures.extend(
            f"Problem {problem_number}: expected it to contain {expected_problem_phrase!r}; actual {actual_problem!r}."
            for problem_number, (expected_problem_phrase, actual_problem) in enumerate(
                zip(expected_exception_content.message_phrases, actual_problems, strict=False), start=1
            )
            if expected_problem_phrase not in actual_problem
        )
        assertion_failures.extend(
            AsserterException._find_exception_content_mismatches(expected_exception_content, actual_voice_agent_restaurant_exception)
        )
        AsserterException._assert_no_mismatches(
            assertion_failures,
            failure_claim=(
                f"{type(actual_voice_agent_restaurant_exception).__name__} must report one problem per expected phrase with the expected "
                f"refusal metadata and context (actual problems: {actual_problems!r})"
            ),
        )

    @staticmethod
    def _assert_no_mismatches(assertion_failures: Iterable[str], *, failure_claim: str) -> None:
        mismatch_messages: list[str] = list(assertion_failures)
        failure_report: str = "\n".join(mismatch_messages)
        assert not failure_report, f"{failure_claim}; {len(mismatch_messages)} mismatches:\n{failure_report}"
