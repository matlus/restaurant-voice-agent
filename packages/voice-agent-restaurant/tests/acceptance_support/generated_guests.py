import secrets
from dataclasses import dataclass
from typing import Final

# Seeded bookings use 555-010-xxxx numbers; generated guests use 555-7xx-xxxx so the two never collide.
GENERATED_PHONE_PREFIX: Final[str] = "5557"
GENERATED_PHONE_SUFFIX_DIGITS: Final[int] = 6


@dataclass(frozen=True)
class GeneratedGuest:
    """A guest whose identity is incidental to the scenario. The phone number is given in the forms a caller says it."""

    guest_name: str
    phone_digits: str
    phone_number_with_brackets: str
    phone_number_with_country_code: str


def create_generated_guest() -> GeneratedGuest:
    phone_digits: str = GENERATED_PHONE_PREFIX + "".join(secrets.choice("0123456789") for _ in range(GENERATED_PHONE_SUFFIX_DIGITS))
    return GeneratedGuest(
        guest_name=f"Guest {secrets.token_hex(3)}",
        phone_digits=phone_digits,
        phone_number_with_brackets=f"({phone_digits[0:3]}) {phone_digits[3:6]}-{phone_digits[6:]}",
        phone_number_with_country_code=f"+1 {phone_digits[0:3]} {phone_digits[3:6]} {phone_digits[6:]}",
    )
