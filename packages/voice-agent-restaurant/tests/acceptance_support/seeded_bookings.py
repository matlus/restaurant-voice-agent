from datetime import date, timedelta
from typing import Final

from acceptance_support.bundled_seed import SeededBookingGuest, read_seeded_booking_guest
from voice_agent_restaurant import DomainFacade, Reservation, ReservationSearchRequest, Weekday

DAYS_PER_WEEK: Final[int] = 7


def derive_next_weekday_date(restaurant_today: date, weekday: Weekday) -> date:
    return restaurant_today + timedelta(days=(list(Weekday).index(weekday) - restaurant_today.weekday()) % DAYS_PER_WEEK)


async def find_seeded_booking(domain_facade: DomainFacade, phone_number: str) -> Reservation:
    """The seeded booking for the phone number, found as its guest finds it: by the phone number, the name it is under and
    its date, the next date its seeded weekday falls on."""
    seeded_booking_guest: SeededBookingGuest = read_seeded_booking_guest(phone_number)
    booking_date: date = derive_next_weekday_date((await domain_facade.get_restaurant_local_now()).date(), Weekday(seeded_booking_guest.weekday))
    found_reservations: list[Reservation] = await domain_facade.find_reservations(
        ReservationSearchRequest(phone_number=phone_number, guest_name=seeded_booking_guest.guest_name, reservation_date=booking_date.isoformat())
    )
    assert len(found_reservations) == 1, (
        f"The seed must hold exactly one upcoming booking for {phone_number} under {seeded_booking_guest.guest_name!r} on {booking_date}; "
        f"found {found_reservations!r}"
    )
    return found_reservations[0]
