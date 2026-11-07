import re
from datetime import date, time
from typing import Final

from voice_agent_restaurant.managers.models.reservation_models import CONFIRMATION_CODE_ALPHABET, CONFIRMATION_CODE_LENGTH

# [0-9] rather than \d: in a str pattern \d also matches non-ASCII digits, which would be stored but never found again.
_DATE_PATTERN: Final[re.Pattern[str]] = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_TIME_PATTERN: Final[re.Pattern[str]] = re.compile(r"([0-9]{1,2}):([0-9]{2})")
_PHONE_DIGITS_PATTERN: Final[re.Pattern[str]] = re.compile(r"[0-9]+")
_PHONE_PATTERN: Final[re.Pattern[str]] = re.compile(r"[0-9]{10}")
_PHONE_SEPARATORS_PATTERN: Final[re.Pattern[str]] = re.compile(r"[\s().+-]")
_CONFIRMATION_CODE_SEPARATORS_PATTERN: Final[re.Pattern[str]] = re.compile(r"[\s-]")
_NORTH_AMERICAN_COUNTRY_CODE: Final[str] = "1"
_NATIONAL_PHONE_NUMBER_LENGTH: Final[int] = 10


class ReservationValueParsing:
    """The accepted text forms of reservation values, and how spoken forms are put into them."""

    @staticmethod
    def as_provided(field_value: str | None) -> str | None:
        """The trimmed value, or None when nothing but whitespace arrived."""
        if field_value is None or field_value.strip() == "":
            return None
        return field_value.strip()

    @staticmethod
    def parse_date(date_text: str) -> date | None:
        if not _DATE_PATTERN.fullmatch(date_text):
            return None
        try:
            return date.fromisoformat(date_text)
        except ValueError:
            return None

    @staticmethod
    def parse_time(time_text: str) -> time | None:
        time_match: re.Match[str] | None = _TIME_PATTERN.fullmatch(time_text)
        if time_match is None:
            return None
        try:
            return time(hour=int(time_match.group(1)), minute=int(time_match.group(2)))
        except ValueError:
            return None

    @staticmethod
    def normalize_phone_number(phone_number: str) -> str:
        """Spoken numbers arrive with spaces, dashes, dots, brackets or a +1 prefix; only the digits identify the line.
        A value that is not digits once separators are removed comes back unchanged, for validation to refuse."""
        phone_digits: str = _PHONE_SEPARATORS_PATTERN.sub("", phone_number)
        if not _PHONE_DIGITS_PATTERN.fullmatch(phone_digits):
            return phone_number
        if len(phone_digits) == _NATIONAL_PHONE_NUMBER_LENGTH + 1 and phone_digits.startswith(_NORTH_AMERICAN_COUNTRY_CODE):
            return phone_digits[1:]
        return phone_digits

    @staticmethod
    def is_phone_number(phone_number: str) -> bool:
        return _PHONE_PATTERN.fullmatch(phone_number) is not None

    @staticmethod
    def normalize_confirmation_code(confirmation_code: str) -> str:
        """Codes are read aloud in groups and in either case, so separators are dropped and letters upper-cased."""
        return _CONFIRMATION_CODE_SEPARATORS_PATTERN.sub("", confirmation_code).upper()

    @staticmethod
    def is_confirmation_code(confirmation_code: str) -> bool:
        return len(confirmation_code) == CONFIRMATION_CODE_LENGTH and all(
            code_character in CONFIRMATION_CODE_ALPHABET for code_character in confirmation_code
        )
