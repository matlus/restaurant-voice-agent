from dataclasses import dataclass
from datetime import date, time
from enum import StrEnum


class Weekday(StrEnum):
    """Weekdays in Python's date.weekday() order, so date.weekday() indexes this enum's members."""

    MONDAY = "monday"
    TUESDAY = "tuesday"
    WEDNESDAY = "wednesday"
    THURSDAY = "thursday"
    FRIDAY = "friday"
    SATURDAY = "saturday"
    SUNDAY = "sunday"


@dataclass(frozen=True)
class OpenWeekday:
    """A weekday on which the restaurant opens, with the hours it keeps."""

    weekday: Weekday
    opens_at: time
    closes_at: time


@dataclass(frozen=True)
class ClosedWeekday:
    """A weekday on which the restaurant does not open at all."""

    weekday: Weekday


type WeekdayHours = OpenWeekday | ClosedWeekday


@dataclass(frozen=True)
class Closure:
    closed_on: date
    reason: str


@dataclass(frozen=True)
class ReservationPolicy:
    seating_duration_minutes: int
    slot_interval_minutes: int
    minimum_party_size: int
    maximum_party_size: int
    booking_window_days: int
    minimum_lead_time_minutes: int
    late_arrival_hold_minutes: int
    large_party_guidance: str


@dataclass(frozen=True)
class RestaurantProfile:
    name: str
    tagline: str
    description: str
    street_address: str
    city: str
    state_or_region: str
    postal_code: str
    phone_number: str
    time_zone: str
    house_notes: list[str]
    reservation_policy: ReservationPolicy


@dataclass(frozen=True)
class OpeningHours:
    """The weekly schedule plus the closures that fall inside the booking window.

    last_seating_minutes_before_close is how long before closing the final table can be seated.
    """

    weekly_hours: list[WeekdayHours]
    upcoming_closures: list[Closure]
    last_seating_minutes_before_close: int


@dataclass(frozen=True)
class DiningTable:
    table_id: str
    seats: int
    area: str
