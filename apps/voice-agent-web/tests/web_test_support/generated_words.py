import secrets
import string
from typing import Final

DEFAULT_GENERATED_WORD_LENGTH: Final[int] = 8


def create_generated_word(word_length: int = DEFAULT_GENERATED_WORD_LENGTH) -> str:
    """A capitalized word whose letters are incidental to the scenario."""
    return "".join(secrets.choice(string.ascii_lowercase) for _ in range(word_length)).capitalize()
