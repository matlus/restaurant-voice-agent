import re
from typing import Final


class GuestNameMatching:
    """Whether the name a guest gives is the name their booking is under. Pure calculation; no store access.

    Case, spacing and punctuation never matter, and every word the guest gives must be in the booked name. A first name
    alone is not enough: the guest must give at least one later word, so "Raman" and "Priya Raman" match "Priya Raman",
    "Garcia" matches "Maria Garcia Lopez", and "Priya" does not. A booking under one word needs exactly that word.
    """

    NAME_WORD_PATTERN: Final[re.Pattern[str]] = re.compile(r"[^\W_]+")

    @classmethod
    def is_name_on_booking(cls, booked_guest_name: str, given_guest_name: str) -> bool:
        booked_name_words: list[str] = cls._get_name_words(booked_guest_name)
        given_name_words: list[str] = cls._get_name_words(given_guest_name)
        if not given_name_words or any(given_name_word not in booked_name_words for given_name_word in given_name_words):
            return False
        later_booked_name_words: list[str] = booked_name_words[1:]
        return not later_booked_name_words or any(given_name_word in later_booked_name_words for given_name_word in given_name_words)

    @classmethod
    def _get_name_words(cls, guest_name: str) -> list[str]:
        return cls.NAME_WORD_PATTERN.findall(guest_name.casefold())
