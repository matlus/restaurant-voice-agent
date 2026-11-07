from collections.abc import Iterable, Sequence
from datetime import time

from voice_agent_restaurant import (
    DishLookupValidationException,
    DishNotFoundException,
    ExceptionAction,
    MenuSearchValidationException,
    NoTableAvailableException,
    ReservationRequestValidationException,
    VoiceAgentRestaurantBaseException,
)

type ValidationException = ReservationRequestValidationException | MenuSearchValidationException | DishLookupValidationException


class AsserterException:
    """Compares a raised exception with the test's expectations and reports every mismatch in one failure.

    Expected message phrases must each appear in the message; the message may say more.
    """

    @staticmethod
    def assert_message_status_and_action_are_as_expected(
        *,
        expected_message_phrases: Iterable[str],
        expected_http_status_code: int,
        expected_exception_action: ExceptionAction,
        actual_exception: VoiceAgentRestaurantBaseException,
    ) -> None:
        assertion_failures: list[str] = AsserterException._find_message_mismatches(expected_message_phrases, actual_exception.message)
        assertion_failures.extend(
            AsserterException._find_status_and_action_mismatches(expected_http_status_code, expected_exception_action, actual_exception)
        )
        AsserterException._assert_no_mismatches(assertion_failures)

    @staticmethod
    def assert_validation_problems_are_as_expected(*, expected_problem_phrases: Sequence[str], actual_exception: ValidationException) -> None:
        """One problem per expected phrase, each phrase in the message, and the metadata every validation refusal carries."""
        assertion_failures: list[str] = []
        if len(actual_exception.validation_problems) != len(expected_problem_phrases):
            assertion_failures.append(
                f"Problem count: expected {len(expected_problem_phrases)}; actual {len(actual_exception.validation_problems)} "
                f"({actual_exception.validation_problems!r})."
            )
        assertion_failures.extend(AsserterException._find_message_mismatches(expected_problem_phrases, actual_exception.message))
        assertion_failures.extend(AsserterException._find_status_and_action_mismatches(400, ExceptionAction.USER_ACTION_REQUIRED, actual_exception))
        AsserterException._assert_no_mismatches(assertion_failures)

    @staticmethod
    def assert_no_table_refusal_is_as_expected(*, expected_alternative_times: Sequence[time], actual_exception: NoTableAvailableException) -> None:
        assertion_failures: list[str] = []
        if actual_exception.alternative_times != list(expected_alternative_times):
            assertion_failures.append(
                f"Alternative times: expected {list(expected_alternative_times)!r}; actual {actual_exception.alternative_times!r}."
            )
        assertion_failures.extend(
            AsserterException._find_message_mismatches(
                [f"{expected_alternative_time:%H:%M}" for expected_alternative_time in expected_alternative_times], actual_exception.message
            )
        )
        assertion_failures.extend(AsserterException._find_status_and_action_mismatches(409, ExceptionAction.USER_ACTION_REQUIRED, actual_exception))
        AsserterException._assert_no_mismatches(assertion_failures)

    @staticmethod
    def assert_dish_not_found_refusal_is_as_expected(*, expected_close_match_names: Sequence[str], actual_exception: DishNotFoundException) -> None:
        assertion_failures: list[str] = []
        if actual_exception.close_match_names != list(expected_close_match_names):
            assertion_failures.append(
                f"Close match names: expected {list(expected_close_match_names)!r}; actual {actual_exception.close_match_names!r}."
            )
        assertion_failures.extend(AsserterException._find_message_mismatches(expected_close_match_names, actual_exception.message))
        assertion_failures.extend(AsserterException._find_status_and_action_mismatches(404, ExceptionAction.USER_ACTION_REQUIRED, actual_exception))
        AsserterException._assert_no_mismatches(assertion_failures)

    @staticmethod
    def _find_message_mismatches(expected_message_phrases: Iterable[str], actual_exception_message: str) -> list[str]:
        return [
            f"Message is missing {expected_message_phrase!r}. Actual message: {actual_exception_message!r}."
            for expected_message_phrase in expected_message_phrases
            if expected_message_phrase not in actual_exception_message
        ]

    @staticmethod
    def _find_status_and_action_mismatches(
        expected_http_status_code: int, expected_exception_action: ExceptionAction, actual_exception: VoiceAgentRestaurantBaseException
    ) -> list[str]:
        assertion_failures: list[str] = []
        if actual_exception.http_status_code != expected_http_status_code:
            assertion_failures.append(f"HTTP status: expected {expected_http_status_code}; actual {actual_exception.http_status_code}.")
        if actual_exception.action != expected_exception_action:
            assertion_failures.append(f"Action: expected {expected_exception_action.value}; actual {actual_exception.action.value}.")
        return assertion_failures

    @staticmethod
    def _assert_no_mismatches(assertion_failures: Iterable[str]) -> None:
        failure_report: str = "\n".join(assertion_failures)
        assert not failure_report, f"Exception assertions failed:\n{failure_report}"
