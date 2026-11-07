from datetime import UTC, datetime
from typing import final, override

from voice_agent_restaurant.managers.clocks.clock_base import ClockBase


@final
class ClockSystem(ClockBase):
    @override
    def now_utc(self) -> datetime:
        return datetime.now(UTC)
