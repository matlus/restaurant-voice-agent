from collections.abc import Iterable, Sequence
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


@dataclass(frozen=True)
class ExpectedExceptionMetadata:
    """What every restaurant exception declares about itself, arranged by the test."""

    http_status_code: int
    exception_action: ExceptionAction
    reason: str
    severity: Severity


class AsserterException:
    """Compares a raised exception with the test's expectations and reports every mismatch in one failure.

    Expected message phrases must each appear in the message; the message may say more.
    """

    @staticmethod
    def assert_message_and_metadata_are_as_expected(
        *,
        expected_message_phrases: Iterable[str],
        expected_exception_metadata: ExpectedExceptionMetadata,
        actual_voice_agent_restaurant_exception: VoiceAgentRestaurantBaseException,
    ) -> None:
        assertion_failures: list[str] = AsserterException._find_message_mismatches(
            expected_message_phrases, actual_voice_agent_restaurant_exception.message
        )
        assertion_failures.extend(AsserterException._find_metadata_mismatches(expected_exception_metadata, actual_voice_agent_restaurant_exception))
        AsserterException._assert_no_mismatches(
            assertion_failures,
            failure_claim=(
                f"{type(actual_voice_agent_restaurant_exception).__name__} must carry the expected message phrases, HTTP status, action, "
                f"reason and severity (actual message: {actual_voice_agent_restaurant_exception.message!r})"
            ),
        )

    @staticmethod
    def assert_validation_problems_are_as_expected(
        *,
        expected_problem_phrases: Sequence[str],
        expected_exception_metadata: ExpectedExceptionMetadata,
        actual_validation_exception: ValidationException,
    ) -> None:
        """One problem per expected phrase, each phrase in the message, and the refusal's metadata."""
        assertion_failures: list[str] = []
        if len(actual_validation_exception.validation_problems) != len(expected_problem_phrases):
            assertion_failures.append(
                f"Problem count: expected {len(expected_problem_phrases)}; actual {len(actual_validation_exception.validation_problems)} "
                f"({actual_validation_exception.validation_problems!r})."
            )
        assertion_failures.extend(AsserterException._find_message_mismatches(expected_problem_phrases, actual_validation_exception.message))
        assertion_failures.extend(AsserterException._find_metadata_mismatches(expected_exception_metadata, actual_validation_exception))
        AsserterException._assert_no_mismatches(
            assertion_failures,
            failure_claim=(
                f"{type(actual_validation_exception).__name__} must report one problem per expected phrase with the validation refusal metadata "
                f"(actual problems: {actual_validation_exception.validation_problems!r})"
            ),
        )

    @staticmethod
    def assert_no_table_refusal_is_as_expected(
        *,
        expected_alternative_times: Sequence[time],
        expected_exception_metadata: ExpectedExceptionMetadata,
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
        AsserterException._assert_no_mismatches(
            assertion_failures,
            failure_claim=(
                f"{type(actual_no_table_available_exception).__name__} must refuse with the expected alternative times and refusal metadata "
                f"(actual message: {actual_no_table_available_exception.message!r})"
            ),
        )

    @staticmethod
    def assert_dish_not_found_refusal_is_as_expected(
        *,
        expected_close_match_names: Sequence[str],
        expected_message_phrases: Iterable[str],
        expected_exception_metadata: ExpectedExceptionMetadata,
        actual_dish_not_found_exception: DishNotFoundException,
    ) -> None:
        """The close matches offered, each named in the message beside the expected phrases, and the refusal's metadata."""
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
        AsserterException._assert_no_mismatches(
            assertion_failures,
            failure_claim=(
                f"{type(actual_dish_not_found_exception).__name__} must refuse with the expected close match names, message and refusal "
                f"metadata (actual message: {actual_dish_not_found_exception.message!r})"
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
    def _assert_no_mismatches(assertion_failures: Iterable[str], *, failure_claim: str) -> None:
        mismatch_messages: list[str] = list(assertion_failures)
        failure_report: str = "\n".join(mismatch_messages)
        assert not failure_report, f"{failure_claim}; {len(mismatch_messages)} mismatches:\n{failure_report}"
