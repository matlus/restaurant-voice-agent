from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import time

from voice_agent_restaurant import (
    DishLookupValidationException,
    DishNotFoundException,
    ExceptionAction,
    MenuSearchValidationException,
    NoTableAvailableException,
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


class AsserterException:
    """Compares a raised exception with the test's expectations and reports every mismatch in one failure.

    Expected message phrases must each appear in the message; the message may say more. Each expected contextual entry
    must be present with its value, and each expected present name must be present with any value; the exception may
    carry other entries.
    """

    @staticmethod
    def assert_message_and_metadata_are_as_expected(
        *,
        expected_message_phrases: Iterable[str],
        expected_exception_metadata: ExpectedExceptionMetadata,
        expected_contextual_data_by_name: Mapping[str, ContextualDataValue],
        actual_voice_agent_restaurant_exception: VoiceAgentRestaurantBaseException,
        expected_present_contextual_data_names: Iterable[str] = (),
    ) -> None:
        assertion_failures: list[str] = AsserterException._find_message_mismatches(
            expected_message_phrases, actual_voice_agent_restaurant_exception.message
        )
        assertion_failures.extend(AsserterException._find_metadata_mismatches(expected_exception_metadata, actual_voice_agent_restaurant_exception))
        assertion_failures.extend(
            AsserterException._find_contextual_data_mismatches(
                expected_contextual_data_by_name, expected_present_contextual_data_names, actual_voice_agent_restaurant_exception
            )
        )
        AsserterException._assert_no_mismatches(
            assertion_failures,
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
        assertion_failures: list[str] = []
        if len(actual_validation_exception.validation_problems) != len(expected_problem_phrases):
            assertion_failures.append(
                f"Problem count: expected {len(expected_problem_phrases)}; actual {len(actual_validation_exception.validation_problems)} "
                f"({actual_validation_exception.validation_problems!r})."
            )
        assertion_failures.extend(AsserterException._find_message_mismatches(expected_problem_phrases, actual_validation_exception.message))
        assertion_failures.extend(AsserterException._find_metadata_mismatches(expected_exception_metadata, actual_validation_exception))
        assertion_failures.extend(
            AsserterException._find_contextual_data_mismatches(expected_contextual_data_by_name, (), actual_validation_exception)
        )
        AsserterException._assert_no_mismatches(
            assertion_failures,
            failure_claim=(
                f"{type(actual_validation_exception).__name__} must report one problem per expected phrase with the validation refusal "
                f"metadata and context (actual problems: {actual_validation_exception.validation_problems!r})"
            ),
        )

    @staticmethod
    def assert_no_table_refusal_is_as_expected(
        *,
        expected_alternative_times: Sequence[time],
        expected_exception_metadata: ExpectedExceptionMetadata,
        expected_contextual_data_by_name: Mapping[str, ContextualDataValue],
        actual_no_table_available_exception: NoTableAvailableException,
    ) -> None:
        assertion_failures: list[str] = []
        if actual_no_table_available_exception.alternative_times != list(expected_alternative_times):
            assertion_failures.append(
                f"Alternative times: expected {list(expected_alternative_times)!r}; actual {actual_no_table_available_exception.alternative_times!r}."
            )
        assertion_failures.extend(
            AsserterException._find_message_mismatches(
                [f"{expected_alternative_time:%H:%M}" for expected_alternative_time in expected_alternative_times],
                actual_no_table_available_exception.message,
            )
        )
        assertion_failures.extend(AsserterException._find_metadata_mismatches(expected_exception_metadata, actual_no_table_available_exception))
        assertion_failures.extend(
            AsserterException._find_contextual_data_mismatches(expected_contextual_data_by_name, (), actual_no_table_available_exception)
        )
        AsserterException._assert_no_mismatches(
            assertion_failures,
            failure_claim=(
                f"{type(actual_no_table_available_exception).__name__} must refuse with the expected alternative times, refusal metadata and context "
                f"(actual message: {actual_no_table_available_exception.message!r})"
            ),
        )

    @staticmethod
    def assert_dish_not_found_refusal_is_as_expected(
        *,
        expected_close_match_names: Sequence[str],
        expected_message_phrases: Iterable[str],
        expected_exception_metadata: ExpectedExceptionMetadata,
        expected_contextual_data_by_name: Mapping[str, ContextualDataValue],
        actual_dish_not_found_exception: DishNotFoundException,
    ) -> None:
        assertion_failures: list[str] = []
        if actual_dish_not_found_exception.close_match_names != list(expected_close_match_names):
            assertion_failures.append(
                f"Close match names: expected {list(expected_close_match_names)!r}; actual {actual_dish_not_found_exception.close_match_names!r}."
            )
        assertion_failures.extend(
            AsserterException._find_message_mismatches(
                [*expected_message_phrases, *expected_close_match_names], actual_dish_not_found_exception.message
            )
        )
        assertion_failures.extend(AsserterException._find_metadata_mismatches(expected_exception_metadata, actual_dish_not_found_exception))
        assertion_failures.extend(
            AsserterException._find_contextual_data_mismatches(expected_contextual_data_by_name, (), actual_dish_not_found_exception)
        )
        AsserterException._assert_no_mismatches(
            assertion_failures,
            failure_claim=(
                f"{type(actual_dish_not_found_exception).__name__} must refuse with the expected close match names, message, refusal "
                f"metadata and context (actual message: {actual_dish_not_found_exception.message!r})"
            ),
        )

    @staticmethod
    def _find_message_mismatches(expected_message_phrases: Iterable[str], actual_exception_message: str) -> list[str]:
        return [
            f"Message is missing {expected_message_phrase!r}. Actual message: {actual_exception_message!r}."
            for expected_message_phrase in expected_message_phrases
            if expected_message_phrase not in actual_exception_message
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
            if actual_contextual_data_by_name.get(contextual_data_name) != expected_contextual_data_value:
                assertion_failures.append(
                    f"Context {contextual_data_name!r}: expected {expected_contextual_data_value!r}; "
                    f"actual {actual_contextual_data_by_name.get(contextual_data_name)!r}."
                )
        assertion_failures.extend(
            f"Context {present_contextual_data_name!r}: expected present; actual absent."
            for present_contextual_data_name in expected_present_contextual_data_names
            if present_contextual_data_name not in actual_contextual_data_by_name
        )
        return assertion_failures

    @staticmethod
    def _assert_no_mismatches(assertion_failures: Iterable[str], *, failure_claim: str) -> None:
        mismatch_messages: list[str] = list(assertion_failures)
        failure_report: str = "\n".join(mismatch_messages)
        assert not failure_report, f"{failure_claim}; {len(mismatch_messages)} mismatches:\n{failure_report}"
