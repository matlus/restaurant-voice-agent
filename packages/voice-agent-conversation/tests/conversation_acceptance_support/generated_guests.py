import secrets
import string
from dataclasses import dataclass
from typing import Final

# Seeded bookings use 555-010-xxxx numbers; generated guests use 555-7xx-xxxx so the two never collide.
GENERATED_PHONE_PREFIX: Final[str] = "5557"
GENERATED_PHONE_SUFFIX_DIGITS: Final[int] = 6
DEFAULT_MINIMUM_NAME_WORD_LENGTH: Final[int] = 4
DEFAULT_MAXIMUM_NAME_WORD_LENGTH: Final[int] = 12
DEFAULT_MINIMUM_NOTE_LENGTH: Final[int] = 12
DEFAULT_MAXIMUM_NOTE_LENGTH: Final[int] = 40
DEFAULT_GUEST_AUDIO_CHUNK_COUNT: Final[int] = 2
# An even count, so every chunk holds whole 16-bit samples.
DEFAULT_GUEST_AUDIO_CHUNK_BYTE_COUNT: Final[int] = 32


@dataclass(frozen=True)
class GeneratedGuest:
    """A guest whose name and phone number are incidental to the scenario. The name has a first and a family name."""

    first_name: str
    family_name: str
    phone_digits: str

    @property
    def guest_name(self) -> str:
        return f"{self.first_name} {self.family_name}"


def create_generated_guest(
    minimum_name_word_length: int = DEFAULT_MINIMUM_NAME_WORD_LENGTH, maximum_name_word_length: int = DEFAULT_MAXIMUM_NAME_WORD_LENGTH
) -> GeneratedGuest:
    """Each name word is between the bounds in length; equal bounds give words of exactly that length."""
    return GeneratedGuest(
        first_name=_create_generated_word(_choose_length(minimum_name_word_length, maximum_name_word_length)).capitalize(),
        family_name=_create_generated_word(_choose_length(minimum_name_word_length, maximum_name_word_length)).capitalize(),
        phone_digits=GENERATED_PHONE_PREFIX + "".join(secrets.choice(string.digits) for _ in range(GENERATED_PHONE_SUFFIX_DIGITS)),
    )


def create_generated_note(minimum_note_length: int = DEFAULT_MINIMUM_NOTE_LENGTH, maximum_note_length: int = DEFAULT_MAXIMUM_NOTE_LENGTH) -> str:
    """A booking note whose words are incidental to the scenario: two words joined by a space, between the bounds in length."""
    note_length: int = _choose_length(minimum_note_length, maximum_note_length)
    first_word_length: int = note_length // 2
    return f"{_create_generated_word(first_word_length).capitalize()} {_create_generated_word(note_length - first_word_length - 1)}"


def create_generated_guest_audio_chunks(
    chunk_count: int = DEFAULT_GUEST_AUDIO_CHUNK_COUNT, chunk_byte_count: int = DEFAULT_GUEST_AUDIO_CHUNK_BYTE_COUNT
) -> list[bytes]:
    """Guest speech whose exact bytes are incidental to the scenario."""
    return [secrets.token_bytes(chunk_byte_count) for _ in range(chunk_count)]


def _choose_length(minimum_length: int, maximum_length: int) -> int:
    return minimum_length + secrets.randbelow(maximum_length - minimum_length + 1)


def _create_generated_word(word_length: int) -> str:
    return "".join(secrets.choice(string.ascii_lowercase) for _ in range(word_length))
