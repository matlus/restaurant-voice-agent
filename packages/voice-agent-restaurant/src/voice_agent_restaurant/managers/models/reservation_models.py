import re
from dataclasses import dataclass
from datetime import date, datetime, time
from enum import StrEnum
from typing import Final

# Confirmation codes avoid letters and digits that sound or look alike when read aloud (B/D/P, I/1, O/0, S/5, Z/2).
CONFIRMATION_CODE_ALPHABET: Final[str] = "ACDEFGHJKMNPQRTUVWXY34679"
CONFIRMATION_CODE_LENGTH: Final[int] = 6
NATIONAL_PHONE_NUMBER_LENGTH: Final[int] = 10
# The stored forms the store matches guests' codes and numbers in exactly; validation puts spoken values into these forms.
# [0-9] rather than \d: in a str pattern \d also matches non-ASCII digits, which would be stored but never found again.
STORED_CONFIRMATION_CODE_PATTERN: Final[re.Pattern[str]] = re.compile(f"[{re.escape(CONFIRMATION_CODE_ALPHABET)}]{{{CONFIRMATION_CODE_LENGTH}}}")
STORED_PHONE_NUMBER_PATTERN: Final[re.Pattern[str]] = re.compile(f"[0-9]{{{NATIONAL_PHONE_NUMBER_LENGTH}}}")


class ReservationStatus(StrEnum):
    BOOKED = "booked"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class Reservation:
    confirmation_code: str
    guest_name: str
    phone_number: str
    party_size: int
    reservation_date: date
    starts_at: time
    ends_at: time
    table_id: str
    notes: str | None
    reservation_status: ReservationStatus


@dataclass(frozen=True)
class AvailabilityRequest:
    """An availability question exactly as it arrived: date as YYYY-MM-DD, time as 24-hour HH:MM."""

    reservation_date: str | None
    reservation_time: str | None
    party_size: int | None


@dataclass(frozen=True)
class AvailabilityResult:
    reservation_date: date
    requested_time: time
    party_size: int
    is_available: bool
    alternative_times: list[time]


@dataclass(frozen=True)
class ReservationRequest:
    """A new booking exactly as it arrived: date as YYYY-MM-DD, time as 24-hour HH:MM."""

    guest_name: str | None
    phone_number: str | None
    party_size: int | None
    reservation_date: str | None
    reservation_time: str | None
    notes: str | None


@dataclass(frozen=True)
class ReservationSearchRequest:
    phone_number: str | None


@dataclass(frozen=True)
class ReservationChangeRequest:
    """A change to a booking. A field left as None keeps its current value."""

    confirmation_code: str | None
    phone_number: str | None
    reservation_date: str | None
    reservation_time: str | None
    party_size: int | None
    notes: str | None


@dataclass(frozen=True)
class ReservationCancellationRequest:
    confirmation_code: str | None
    phone_number: str | None


@dataclass(frozen=True)
class BookingWindow:
    """When a booking may start, judged at restaurant_now: not in the past and on or before last_date."""

    restaurant_now: datetime
    last_date: date


@dataclass(frozen=True)
class RequestedSeating:
    """When a party wants to sit, after validation."""

    reservation_date: date
    starts_at: time
    party_size: int


@dataclass(frozen=True)
class ReservationIdentity:
    """What identifies a booking to a caller: its confirmation code and the phone number it was made with."""

    confirmation_code: str
    phone_number: str


@dataclass(frozen=True)
class ValidatedReservationRequest:
    guest_name: str
    phone_number: str
    notes: str | None
    requested_seating: RequestedSeating


@dataclass(frozen=True)
class SeatingChange:
    """A change to when a party sits or how many sit. A field left as None keeps the booking's current value."""

    reservation_date: date | None
    starts_at: time | None
    party_size: int | None


@dataclass(frozen=True)
class ValidatedReservationChange:
    """A validated change. Notes left as None keep the booking's current notes."""

    reservation_identity: ReservationIdentity
    seating_change: SeatingChange
    notes: str | None


@dataclass(frozen=True)
class Seating:
    """A table held from starts_at until ends_at by one booked reservation."""

    confirmation_code: str
    table_id: str
    starts_at: time
    ends_at: time


@dataclass(frozen=True)
class NewReservation:
    """A booking ready for the store, which assigns its confirmation code and seats it at the first free candidate table."""

    guest_name: str
    phone_number: str
    party_size: int
    reservation_date: date
    starts_at: time
    ends_at: time
    notes: str | None


@dataclass(frozen=True)
class BookedSchedule:
    """Everything about a booking that a change can rewrite: when and where it sits, for how many, and its notes."""

    party_size: int
    reservation_date: date
    starts_at: time
    ends_at: time
    table_id: str
    notes: str | None


@dataclass(frozen=True)
class ReservationReschedule:
    """New seating details for an existing booking, which the store moves to the first free candidate table.

    current_booked_schedule is the booking as it stood when the change was decided; the store applies the change only while
    the booking still stands that way.
    """

    confirmation_code: str
    current_booked_schedule: BookedSchedule
    party_size: int
    reservation_date: date
    starts_at: time
    ends_at: time
    notes: str | None
