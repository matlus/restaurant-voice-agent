from datetime import time
from typing import Final

MINUTES_PER_HOUR: Final[int] = 60


def to_minutes_after_midnight(time_of_day: time) -> int:
    return time_of_day.hour * MINUTES_PER_HOUR + time_of_day.minute


def from_minutes_after_midnight(minutes_after_midnight: int) -> time:
    return time(hour=minutes_after_midnight // MINUTES_PER_HOUR, minute=minutes_after_midnight % MINUTES_PER_HOUR)
