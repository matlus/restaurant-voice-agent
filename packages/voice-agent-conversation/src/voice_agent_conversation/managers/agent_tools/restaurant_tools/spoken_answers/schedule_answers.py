from dataclasses import dataclass
from datetime import date
from typing import Final, final

from voice_agent_conversation.managers.agent_tools.restaurant_tools.spoken_answers.spoken_forms import SpokenForms
from voice_agent_restaurant import AvailabilityResult, ClosedWeekday, Closure, OpeningHours, OpenWeekday, Weekday, WeekdayHours


@final
@dataclass(frozen=True)
class WeekdayHoursAnswer:
    """One weekday's hours, such as '5 PM to 10 PM', or 'closed'."""

    weekday: Weekday
    hours: str


@final
@dataclass(frozen=True)
class OpeningHoursAnswer:
    weekly_hours: list[WeekdayHoursAnswer]
    upcoming_closures: list[Closure]
    last_seating_minutes_before_close: int


@final
@dataclass(frozen=True)
class AvailabilityAnswer:
    reservation_date: date
    requested_time: str
    party_size: int
    is_available: bool
    alternative_times: list[str]


@final
class ScheduleAnswerMapping:
    """Turns the restaurant's hours and availability into answers whose times the agent can say as given."""

    CLOSED_HOURS: Final[str] = "closed"

    @classmethod
    def to_opening_hours_answer(cls, opening_hours: OpeningHours) -> OpeningHoursAnswer:
        return OpeningHoursAnswer(
            weekly_hours=[cls._to_weekday_hours_answer(weekday_hours) for weekday_hours in opening_hours.weekly_hours],
            upcoming_closures=opening_hours.upcoming_closures,
            last_seating_minutes_before_close=opening_hours.last_seating_minutes_before_close,
        )

    @staticmethod
    def to_availability_answer(availability_result: AvailabilityResult) -> AvailabilityAnswer:
        return AvailabilityAnswer(
            reservation_date=availability_result.reservation_date,
            requested_time=SpokenForms.speak_time(availability_result.requested_time),
            party_size=availability_result.party_size,
            is_available=availability_result.is_available,
            alternative_times=[SpokenForms.speak_time(alternative_time) for alternative_time in availability_result.alternative_times],
        )

    @classmethod
    def _to_weekday_hours_answer(cls, weekday_hours: WeekdayHours) -> WeekdayHoursAnswer:
        match weekday_hours:
            case OpenWeekday(weekday=weekday, opens_at=opens_at, closes_at=closes_at):
                return WeekdayHoursAnswer(weekday=weekday, hours=f"{SpokenForms.speak_time(opens_at)} to {SpokenForms.speak_time(closes_at)}")
            case ClosedWeekday(weekday=weekday):
                return WeekdayHoursAnswer(weekday=weekday, hours=cls.CLOSED_HOURS)
