import re
from typing import Final


class GuestNameMatching:
    """Whether the name a guest gives is the name their booking is under. Pure calculation; no store access.

    Case, spacing and punctuation never matter. The guest must give the last word of the booked name, the family name,
    and may add any other words of it, so "Raman" and "Priya Raman" both match "Priya Raman", but "Priya" alone does not.
    """

    NAME_WORD_PATTERN: Final[re.Pattern[str]] = re.compile(r"[^\W_]+")

    @classmethod
    def is_name_on_booking(cls, booked_guest_name: str, given_guest_name: str) -> bool:
        booked_name_words: list[str] = cls._get_name_words(booked_guest_name)
        given_name_words: list[str] = cls._get_name_words(given_guest_name)
        if not booked_name_words or not given_name_words:
            return False
        return booked_name_words[-1] in given_name_words and all(given_name_word in booked_name_words for given_name_word in given_name_words)

    @classmethod
    def _get_name_words(cls, guest_name: str) -> list[str]:
        return cls.NAME_WORD_PATTERN.findall(guest_name.casefold())
