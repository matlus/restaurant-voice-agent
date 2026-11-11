import secrets
import string
from dataclasses import dataclass
from typing import Final

# Seeded bookings use 555-010-xxxx numbers; generated guests use 555-7xx-xxxx so the two never collide.
GENERATED_PHONE_PREFIX: Final[str] = "5557"
GENERATED_PHONE_SUFFIX_DIGITS: Final[int] = 6
GENERATED_NAME_WORD_LENGTH: Final[int] = 8


@dataclass(frozen=True)
class GeneratedGuest:
    """A guest whose name and phone number are incidental to the scenario. The name has a first and a family name."""

    first_name: str
    family_name: str
    phone_digits: str

    @property
    def guest_name(self) -> str:
        return f"{self.first_name} {self.family_name}"


def create_generated_guest() -> GeneratedGuest:
    return GeneratedGuest(
        first_name=_create_generated_word(GENERATED_NAME_WORD_LENGTH).capitalize(),
        family_name=_create_generated_word(GENERATED_NAME_WORD_LENGTH).capitalize(),
        phone_digits=GENERATED_PHONE_PREFIX + "".join(secrets.choice(string.digits) for _ in range(GENERATED_PHONE_SUFFIX_DIGITS)),
    )


def create_generated_note() -> str:
    """A booking note whose words are incidental to the scenario."""
    return f"{_create_generated_word(GENERATED_NAME_WORD_LENGTH).capitalize()} {_create_generated_word(GENERATED_NAME_WORD_LENGTH)}"


def _create_generated_word(word_length: int) -> str:
    return "".join(secrets.choice(string.ascii_lowercase) for _ in range(word_length))
