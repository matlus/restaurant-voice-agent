from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Final

from voice_agent_restaurant.managers.models.reservation_models import BookingWindow, RequestedSeating, Seating, SeatingChange
from voice_agent_restaurant.managers.models.restaurant_models import DiningTable, OpenWeekday, Weekday, WeekdayHours

MINUTES_PER_HOUR: Final[int] = 60
MINUTES_PER_DAY: Final[int] = 24 * MINUTES_PER_HOUR


@dataclass(frozen=True)
class SeatingWindow:
    """The first and last times a table can be seated on one day; every seating ends by closing time."""

    first_seating_time: time
    last_seating_time: time


@dataclass(frozen=True)
class SeatingRhythm:
    """How seatings are laid out: the minutes between bookable start times and the minutes each party holds its table."""

    slot_interval_minutes: int
    seating_duration_minutes: int


@dataclass(frozen=True)
class SeatingDay:
    """What decides the open times on one date for one party: when seating is possible, which tables fit, and who holds them."""

    reservation_date: date
    seating_window: SeatingWindow
    fitting_tables: list[DiningTable]
    seatings: list[Seating]


class SeatingRules:
    """When tables can be seated and which tables a party may take. Pure calculation; no store access."""

    MAXIMUM_ALTERNATIVE_TIMES: Final[int] = 3
    _NOON_HOUR: Final[int] = 12

    @staticmethod
    def weekday_of(calendar_date: date) -> Weekday:
        return list(Weekday)[calendar_date.weekday()]

    @staticmethod
    def get_booking_window(restaurant_now: datetime, booking_window_days: int) -> BookingWindow:
        return BookingWindow(restaurant_now=restaurant_now, last_date=restaurant_now.date() + timedelta(days=booking_window_days))

    @classmethod
    def get_seating_window(cls, weekday_hours: WeekdayHours, seating_duration_minutes: int) -> SeatingWindow | None:
        """The day's seating window, or None when the restaurant does not open or no full seating fits before closing."""
        if not isinstance(weekday_hours, OpenWeekday):
            return None
        last_seating_minutes: int = cls._to_minutes(weekday_hours.closes_at) - seating_duration_minutes
        if last_seating_minutes < cls._to_minutes(weekday_hours.opens_at):
            return None
        return SeatingWindow(first_seating_time=weekday_hours.opens_at, last_seating_time=cls._from_minutes(last_seating_minutes))

    @staticmethod
    def apply_seating_change(current_requested_seating: RequestedSeating, seating_change: SeatingChange) -> RequestedSeating:
        return RequestedSeating(
            reservation_date=(
                current_requested_seating.reservation_date if seating_change.reservation_date is None else seating_change.reservation_date
            ),
            starts_at=current_requested_seating.starts_at if seating_change.starts_at is None else seating_change.starts_at,
            party_size=current_requested_seating.party_size if seating_change.party_size is None else seating_change.party_size,
        )

    @staticmethod
    def is_within_window(requested_time: time, seating_window: SeatingWindow) -> bool:
        return seating_window.first_seating_time <= requested_time <= seating_window.last_seating_time

    @classmethod
    def read_as_seatable_time(cls, requested_time: time, seating_window: SeatingWindow) -> time:
        """Callers rarely say AM or PM, so "6:30" can arrive as 06:30. A morning time the restaurant cannot seat is read
        as the same time in the evening when that one can be seated; any other time is kept as it is."""
        if requested_time.hour >= cls._NOON_HOUR or cls.is_within_window(requested_time, seating_window):
            return requested_time
        evening_time: time = requested_time.replace(hour=requested_time.hour + cls._NOON_HOUR)
        return evening_time if cls.is_within_window(evening_time, seating_window) else requested_time

    @classmethod
    def read_as_seatable_time_on(cls, weekday_hours: WeekdayHours, requested_time: time, seating_duration_minutes: int) -> time:
        """The requested time read as callers say it on a day with these hours. A day the restaurant does not open keeps
        the time as it is; whether that day can be booked is decided separately."""
        seating_window: SeatingWindow | None = cls.get_seating_window(weekday_hours, seating_duration_minutes)
        return requested_time if seating_window is None else cls.read_as_seatable_time(requested_time, seating_window)

    @classmethod
    def get_ends_at(cls, starts_at: time, seating_duration_minutes: int) -> time:
        return cls._shift(starts_at, seating_duration_minutes)

    @staticmethod
    def has_started(reservation_date: date, starts_at: time, restaurant_now: datetime) -> bool:
        return datetime.combine(reservation_date, starts_at, tzinfo=restaurant_now.tzinfo) <= restaurant_now

    @staticmethod
    def is_still_upcoming(reservation_date: date, ends_at: time, restaurant_now: datetime) -> bool:
        return reservation_date > restaurant_now.date() or (reservation_date == restaurant_now.date() and ends_at > restaurant_now.time())

    @staticmethod
    def get_fitting_tables(dining_tables: Iterable[DiningTable], party_size: int) -> list[DiningTable]:
        """Tables that seat the party, smallest first, so large tables stay free for large parties."""
        return sorted(
            (dining_table for dining_table in dining_tables if dining_table.seats >= party_size),
            key=lambda dining_table: (dining_table.seats, dining_table.table_id),
        )

    @staticmethod
    def get_candidate_table_ids_keeping_current(fitting_tables: Iterable[DiningTable], current_table_id: str) -> list[str]:
        """The fitting tables in their usual order, except that the guest's current table comes first when it still fits,
        so a change never moves a guest for no reason."""
        return sorted((fitting_table.table_id for fitting_table in fitting_tables), key=lambda table_id: table_id != current_table_id)

    @staticmethod
    def has_free_table(fitting_tables: Iterable[DiningTable], seatings: Sequence[Seating], starts_at: time, ends_at: time) -> bool:
        return any(
            not any(
                seating.table_id == fitting_table.table_id and seating.starts_at < ends_at and starts_at < seating.ends_at for seating in seatings
            )
            for fitting_table in fitting_tables
        )

    @classmethod
    def get_alternative_times(
        cls, seating_day: SeatingDay, requested_time: time, seating_rhythm: SeatingRhythm, restaurant_now: datetime, kept_time: time | None
    ) -> list[time]:
        """Up to MAXIMUM_ALTERNATIVE_TIMES other bookable times with a free fitting table, nearest to the requested time, in time order.
        kept_time, the time a guest moving their booking already holds for the same party that day, is not offered: taking it
        would be no move at all."""
        open_slot_times: list[time] = [
            open_slot_time
            for open_slot_time in cls._get_open_slot_times(seating_day, requested_time, seating_rhythm, restaurant_now)
            if open_slot_time != kept_time
        ]
        return sorted(cls._get_nearest_slot_times(open_slot_times, requested_time))

    @classmethod
    def _get_open_slot_times(
        cls, seating_day: SeatingDay, requested_time: time, seating_rhythm: SeatingRhythm, restaurant_now: datetime
    ) -> list[time]:
        return [
            slot_time
            for slot_time in cls._get_slot_times(seating_day.seating_window, seating_rhythm.slot_interval_minutes)
            if slot_time != requested_time
            and cls._is_still_bookable(seating_day.reservation_date, slot_time, restaurant_now)
            and cls.has_free_table(
                seating_day.fitting_tables, seating_day.seatings, slot_time, cls.get_ends_at(slot_time, seating_rhythm.seating_duration_minutes)
            )
        ]

    @staticmethod
    def _is_still_bookable(reservation_date: date, slot_time: time, restaurant_now: datetime) -> bool:
        """A slot starting right now can still be offered; one that has already begun cannot."""
        return datetime.combine(reservation_date, slot_time, tzinfo=restaurant_now.tzinfo) >= restaurant_now

    @classmethod
    def _get_nearest_slot_times(cls, open_slot_times: Sequence[time], requested_time: time) -> list[time]:
        requested_minutes: int = cls._to_minutes(requested_time)
        return sorted(open_slot_times, key=lambda slot_time: abs(cls._to_minutes(slot_time) - requested_minutes))[: cls.MAXIMUM_ALTERNATIVE_TIMES]

    @classmethod
    def _get_slot_times(cls, seating_window: SeatingWindow, slot_interval_minutes: int) -> list[time]:
        return [
            cls._from_minutes(slot_minutes)
            for slot_minutes in range(
                cls._to_minutes(seating_window.first_seating_time), cls._to_minutes(seating_window.last_seating_time) + 1, slot_interval_minutes
            )
        ]

    @classmethod
    def _shift(cls, time_of_day: time, minutes: int) -> time:
        # Wraps at midnight. No wrap occurs in practice: the seed reader refuses opening hours that close at or after
        # midnight, so every seating window, and every seating it holds, lies inside one calendar day.
        return cls._from_minutes((cls._to_minutes(time_of_day) + minutes) % MINUTES_PER_DAY)

    @staticmethod
    def _to_minutes(time_of_day: time) -> int:
        return time_of_day.hour * MINUTES_PER_HOUR + time_of_day.minute

    @staticmethod
    def _from_minutes(minutes_after_midnight: int) -> time:
        return time(hour=minutes_after_midnight // MINUTES_PER_HOUR, minute=minutes_after_midnight % MINUTES_PER_HOUR)
