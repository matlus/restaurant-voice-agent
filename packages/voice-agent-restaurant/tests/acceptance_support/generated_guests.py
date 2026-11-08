import secrets
import string
from dataclasses import dataclass
from typing import Final

# Seeded bookings use 555-010-xxxx numbers; generated guests use 555-7xx-xxxx so the two never collide.
GENERATED_PHONE_PREFIX: Final[str] = "5557"
GENERATED_PHONE_SUFFIX_DIGITS: Final[int] = 6
DEFAULT_MINIMUM_GUEST_NAME_LENGTH: Final[int] = 8
DEFAULT_MAXIMUM_GUEST_NAME_LENGTH: Final[int] = 24
GENERATED_NOTE_WORD_LENGTH: Final[int] = 6
DEFAULT_NOTE_WORD_COUNT: Final[int] = 3
DEFAULT_MINIMUM_NOTE_LENGTH: Final[int] = DEFAULT_NOTE_WORD_COUNT * GENERATED_NOTE_WORD_LENGTH + (DEFAULT_NOTE_WORD_COUNT - 1)
DEFAULT_MAXIMUM_NOTE_LENGTH: Final[int] = DEFAULT_MINIMUM_NOTE_LENGTH


@dataclass(frozen=True)
class GeneratedGuest:
    """A guest whose identity is incidental to the scenario. The phone number is given in the forms a caller says it."""

    guest_name: str
    phone_digits: str
    phone_number_with_brackets: str
    phone_number_with_country_code: str


def create_generated_guest(
    minimum_guest_name_length: int = DEFAULT_MINIMUM_GUEST_NAME_LENGTH, maximum_guest_name_length: int = DEFAULT_MAXIMUM_GUEST_NAME_LENGTH
) -> GeneratedGuest:
    """Equal bounds give a guest name of exactly that length."""
    guest_name_length: int = minimum_guest_name_length + secrets.randbelow(maximum_guest_name_length - minimum_guest_name_length + 1)
    phone_digits: str = GENERATED_PHONE_PREFIX + "".join(secrets.choice(string.digits) for _ in range(GENERATED_PHONE_SUFFIX_DIGITS))
    return GeneratedGuest(
        guest_name=_create_generated_word(guest_name_length).capitalize(),
        phone_digits=phone_digits,
        phone_number_with_brackets=f"({phone_digits[0:3]}) {phone_digits[3:6]}-{phone_digits[6:]}",
        phone_number_with_country_code=f"+1 {phone_digits[0:3]} {phone_digits[3:6]} {phone_digits[6:]}",
    )


def create_generated_note(minimum_note_length: int = DEFAULT_MINIMUM_NOTE_LENGTH, maximum_note_length: int = DEFAULT_MAXIMUM_NOTE_LENGTH) -> str:
    """A booking note whose words are incidental to the scenario. Equal bounds give a note of exactly that length.

    The note never starts or ends with a space, so trimming leaves its length unchanged.
    """
    note_length: int = minimum_note_length + secrets.randbelow(maximum_note_length - minimum_note_length + 1)
    note_characters: list[str] = list(_create_generated_word(note_length))
    space_position: int
    for space_position in range(GENERATED_NOTE_WORD_LENGTH, note_length - 1, GENERATED_NOTE_WORD_LENGTH + 1):
        note_characters[space_position] = " "
    return "".join(note_characters).capitalize()


def _create_generated_word(word_length: int) -> str:
    return "".join(secrets.choice(string.ascii_lowercase) for _ in range(word_length))
