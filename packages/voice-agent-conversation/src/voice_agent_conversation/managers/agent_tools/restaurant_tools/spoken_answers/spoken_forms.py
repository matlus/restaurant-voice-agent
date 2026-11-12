from datetime import time
from typing import Final, final


@final
class SpokenForms:
    """Times and prices the way people say them on the phone, so the voice model can read an answer aloud as given."""

    CENTS_PER_DOLLAR: Final[int] = 100
    NOON: Final[time] = time(12, 0)
    MIDNIGHT: Final[time] = time(0, 0)
    HOURS_ON_A_CLOCK_FACE: Final[int] = 12

    @classmethod
    def speak_time(cls, clock_time: time) -> str:
        """Such as '5 PM', '6:30 PM', 'noon' or 'midnight'."""
        if clock_time == cls.NOON:
            return "noon"
        if clock_time == cls.MIDNIGHT:
            return "midnight"
        spoken_hour: int = clock_time.hour % cls.HOURS_ON_A_CLOCK_FACE or cls.HOURS_ON_A_CLOCK_FACE
        spoken_minutes: str = "" if clock_time.minute == 0 else f":{clock_time.minute:02d}"
        meridiem: str = "AM" if clock_time.hour < cls.HOURS_ON_A_CLOCK_FACE else "PM"
        return f"{spoken_hour}{spoken_minutes} {meridiem}"

    @classmethod
    def speak_price(cls, price_cents: int) -> str:
        """Such as '$34' or '$12.50'."""
        dollars: int
        cents: int
        dollars, cents = divmod(price_cents, cls.CENTS_PER_DOLLAR)
        return f"${dollars}" if cents == 0 else f"${dollars}.{cents:02d}"
