import re
from datetime import date, time
from typing import Final

from voice_agent_restaurant.managers.models.reservation_models import (
    NATIONAL_PHONE_NUMBER_LENGTH,
    STORED_CONFIRMATION_CODE_PATTERN,
    STORED_PHONE_NUMBER_PATTERN,
)

# [0-9] rather than \d: in a str pattern \d also matches non-ASCII digits, which would be stored but never found again.
_DATE_PATTERN: Final[re.Pattern[str]] = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_TIME_PATTERN: Final[re.Pattern[str]] = re.compile(r"([0-9]{1,2}):([0-9]{2})")
# The way a time is said aloud: "6 PM", "6:30pm", "6:30 p.m.".
_TWELVE_HOUR_TIME_PATTERN: Final[re.Pattern[str]] = re.compile(r"([0-9]{1,2})(?::([0-9]{2}))?\s*([AaPp])\.?\s*[Mm]\.?")
_HOURS_ON_A_TWELVE_HOUR_CLOCK: Final[int] = 12
_PHONE_DIGITS_PATTERN: Final[re.Pattern[str]] = re.compile(r"[0-9]+")
_PHONE_SEPARATORS_PATTERN: Final[re.Pattern[str]] = re.compile(r"[\s().+-]")
_CONFIRMATION_CODE_SEPARATORS_PATTERN: Final[re.Pattern[str]] = re.compile(r"[\s-]")
_NORTH_AMERICAN_COUNTRY_CODE: Final[str] = "1"


class ReservationValueParsing:
    """The accepted text forms of reservation values, and how spoken forms are put into them."""

    @staticmethod
    def as_provided(spoken_field_text: str | None) -> str | None:
        if spoken_field_text is None or spoken_field_text.strip() == "":
            return None
        return spoken_field_text.strip()

    @staticmethod
    def parse_date(date_text: str) -> date | None:
        if not _DATE_PATTERN.fullmatch(date_text):
            return None
        try:
            return date.fromisoformat(date_text)
        except ValueError:
            return None

    @classmethod
    def parse_time(cls, time_text: str) -> time | None:
        """A 24-hour HH:MM time, or a 12-hour time with AM or PM as callers say it."""
        time_match: re.Match[str] | None = _TIME_PATTERN.fullmatch(time_text)
        if time_match is not None:
            return cls._to_time(int(time_match.group(1)), int(time_match.group(2)))
        twelve_hour_match: re.Match[str] | None = _TWELVE_HOUR_TIME_PATTERN.fullmatch(time_text)
        if twelve_hour_match is None:
            return None
        hour: int = int(twelve_hour_match.group(1))
        if not 1 <= hour <= _HOURS_ON_A_TWELVE_HOUR_CLOCK:
            return None
        hour_after_midnight: int = hour % _HOURS_ON_A_TWELVE_HOUR_CLOCK
        if twelve_hour_match.group(3).upper() == "P":
            hour_after_midnight += _HOURS_ON_A_TWELVE_HOUR_CLOCK
        return cls._to_time(hour_after_midnight, int(twelve_hour_match.group(2) or 0))

    @staticmethod
    def _to_time(hour: int, minute: int) -> time | None:
        try:
            return time(hour=hour, minute=minute)
        except ValueError:
            return None

    @staticmethod
    def normalize_phone_number(phone_number: str) -> str:
        """Spoken numbers arrive with spaces, dashes, dots, brackets or a +1 prefix; only the digits identify the line.
        A value that is not digits once separators are removed comes back unchanged, for validation to refuse."""
        phone_digits: str = _PHONE_SEPARATORS_PATTERN.sub("", phone_number)
        if not _PHONE_DIGITS_PATTERN.fullmatch(phone_digits):
            return phone_number
        if len(phone_digits) == NATIONAL_PHONE_NUMBER_LENGTH + 1 and phone_digits.startswith(_NORTH_AMERICAN_COUNTRY_CODE):
            return phone_digits[1:]
        return phone_digits

    @staticmethod
    def is_phone_number(phone_number: str) -> bool:
        return STORED_PHONE_NUMBER_PATTERN.fullmatch(phone_number) is not None

    @staticmethod
    def normalize_confirmation_code(confirmation_code: str) -> str:
        """Codes are read aloud in groups and in either case, so separators are dropped and letters upper-cased."""
        return _CONFIRMATION_CODE_SEPARATORS_PATTERN.sub("", confirmation_code).upper()

    @staticmethod
    def is_confirmation_code(confirmation_code: str) -> bool:
        return STORED_CONFIRMATION_CODE_PATTERN.fullmatch(confirmation_code) is not None
