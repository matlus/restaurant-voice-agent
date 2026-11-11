from typing import ClassVar, final, override

from pydantic import BaseModel, ConfigDict, Field

from voice_agent_conversation.managers.agent_tools.agent_tool_base import AgentToolBase
from voice_agent_conversation.managers.agent_tools.restaurant_tools.booking_answers import BookingAnswerMapping, BookingSummary
from voice_agent_restaurant import DomainFacade as RestaurantDomainFacade, Reservation, ReservationSearchRequest


@final
class FindBookingsInput(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    phone_number: str = Field(description="The phone number the booking was made with, digits as spoken.")
    guest_name: str = Field(description="The name the booking is under, as the caller says it. The family name is enough.")
    reservation_date: str = Field(description="The date of the booking, as YYYY-MM-DD.")


@final
class AgentToolFindBookings(AgentToolBase[FindBookingsInput, list[BookingSummary]]):
    def __init__(self, restaurant_domain_facade: RestaurantDomainFacade) -> None:
        self._restaurant_domain_facade: RestaurantDomainFacade = restaurant_domain_facade

    @property
    @override
    def name(self) -> str:
        return "find_bookings"

    @property
    @override
    def description(self) -> str:
        return (
            "Lists the caller's upcoming bookings on one date, found by the phone number, name and date they are booked under, "
            "each with its time and party size. Use it when the caller wants to check, change or cancel a booking but does not "
            "have the confirmation code. It never gives the confirmation code."
        )

    @property
    @override
    def input_model(self) -> type[FindBookingsInput]:
        return FindBookingsInput

    @override
    async def run(self, tool_input: FindBookingsInput) -> list[BookingSummary]:
        found_reservations: list[Reservation] = await self._restaurant_domain_facade.find_reservations(
            ReservationSearchRequest(
                phone_number=tool_input.phone_number, guest_name=tool_input.guest_name, reservation_date=tool_input.reservation_date
            )
        )
        return [BookingAnswerMapping.to_booking_summary(found_reservation) for found_reservation in found_reservations]
