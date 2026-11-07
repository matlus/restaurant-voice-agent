import re
from dataclasses import dataclass
from datetime import date, time
from typing import Final

from voice_agent_restaurant import Reservation, ReservationStatus

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
        expected_values_by_name: dict[str, object] = {
            "guest_name": expected_new_reservation.guest_name,
            "phone_number": expected_new_reservation.phone_number,
            "party_size": expected_new_reservation.party_size,
            "reservation_date": expected_new_reservation.reservation_date,
            "starts_at": expected_new_reservation.starts_at,
            "ends_at": expected_new_reservation.ends_at,
            "table_id": expected_new_reservation.table_id,
            "notes": expected_new_reservation.notes,
            "reservation_status": expected_new_reservation.reservation_status,
        }
        value_name: str
        expected_value: object
        for value_name, expected_value in expected_values_by_name.items():
            actual_value: object = getattr(actual_reservation, value_name)
            if actual_value != expected_value:
                assertion_failures.append(f"{value_name}: expected {expected_value!r}; actual {actual_value!r}.")
        failure_report: str = "\n".join(assertion_failures)
        assert not failure_report, f"New reservation assertions failed:\n{failure_report}"
