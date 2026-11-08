import re
from dataclasses import dataclass, fields
from datetime import date, time
from typing import Final

from voice_agent_restaurant import Reservation, ReservationStatus

# Mirrors the store's CONFIRMATION_CODE_ALPHABET and CONFIRMATION_CODE_LENGTH: the alphabet omits letters and digits
# that sound or look alike when a code is read aloud over the phone (B/D/P, I/1, O/0, S/5, Z/2).
CONFIRMATION_CODE_PATTERN: Final[re.Pattern[str]] = re.compile(r"[ACDEFGHJKMNPQRTUVWXY34679]{6}")


@dataclass(frozen=True)
class ExpectedNewReservation:
    """Every value a new booking must hold. The store assigns the confirmation code, so only its form is known."""

    guest_name: str
    phone_number: str
    party_size: int
    reservation_date: date
    starts_at: time
    ends_at: time
    table_id: str
    notes: str | None
    reservation_status: ReservationStatus


class AsserterReservation:
    @staticmethod
    def assert_new_reservation_is_as_expected(expected_new_reservation: ExpectedNewReservation, actual_reservation: Reservation) -> None:
        assertion_failures: list[str] = []
        if CONFIRMATION_CODE_PATTERN.fullmatch(actual_reservation.confirmation_code) is None:
            assertion_failures.append(
                f"Confirmation code: expected six letters and digits that read aloud clearly; actual {actual_reservation.confirmation_code!r}."
            )
        for expected_field in fields(expected_new_reservation):
            expected_value: object = getattr(expected_new_reservation, expected_field.name)
            actual_value: object = getattr(actual_reservation, expected_field.name)
            if actual_value != expected_value:
                assertion_failures.append(f"{expected_field.name}: expected {expected_value!r}; actual {actual_value!r}.")
        failure_report: str = "\n".join(assertion_failures)
        compared_property_count: int = len(fields(expected_new_reservation)) + 1
        assert not failure_report, (
            f"The booking created for guest {expected_new_reservation.guest_name!r} on {expected_new_reservation.reservation_date.isoformat()} "
            f"(confirmation code {actual_reservation.confirmation_code!r}) must hold every booked value; "
            f"{len(assertion_failures)} of {compared_property_count} compared properties mismatched:\n{failure_report}"
        )
