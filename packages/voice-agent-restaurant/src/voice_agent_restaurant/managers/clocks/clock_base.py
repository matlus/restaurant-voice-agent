from abc import ABC, abstractmethod
from datetime import datetime


class ClockBase(ABC):
    """The domain's only source of the current time, so tests can fix "now"."""

    @abstractmethod
    def now_utc(self) -> datetime:
        """Returns the current instant as a timezone-aware UTC datetime."""
