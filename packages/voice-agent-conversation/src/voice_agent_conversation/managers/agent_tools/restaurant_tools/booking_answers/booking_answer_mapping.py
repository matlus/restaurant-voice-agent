from dataclasses import dataclass
from datetime import date
from typing import final

from voice_agent_restaurant import Reservation


@final
@dataclass(frozen=True)
class BookingSummary:
    """What the agent may say about a booking the caller found, changed or cancelled: when, and for how many. The time
    is 24-hour HH:MM, the form the by-details tools take back, so a looked-up booking can be named exactly as given.

    It leaves out the confirmation code, so a booking found without the code never reveals it, and the name, phone number
    and notes, which a guest wrote and the agent has no need to read back.
    """

    reservation_date: date
    reservation_time: str
    party_size: int


@final
@dataclass(frozen=True)
class BookingConfirmation:
    """What the agent reads back once it books a table: the new confirmation code and the details the caller just gave."""

    confirmation_code: str
    guest_name: str
    reservation_date: date
    reservation_time: str
    party_size: int
    notes: str | None


@final
class BookingAnswerMapping:
    """Turns the restaurant's bookings into the answers the agent reads, keeping only what it must say."""

    @staticmethod
    def to_booking_summary(reservation: Reservation) -> BookingSummary:
        return BookingSummary(
            reservation_date=reservation.reservation_date, reservation_time=f"{reservation.starts_at:%H:%M}", party_size=reservation.party_size
        )

    @staticmethod
    def to_booking_confirmation(reservation: Reservation) -> BookingConfirmation:
        return BookingConfirmation(
            confirmation_code=reservation.confirmation_code,
            guest_name=reservation.guest_name,
            reservation_date=reservation.reservation_date,
            reservation_time=f"{reservation.starts_at:%H:%M}",
            party_size=reservation.party_size,
            notes=reservation.notes,
        )
