from typing import ClassVar, final, override

from pydantic import BaseModel, ConfigDict, Field

from voice_agent_conversation.managers.agent_tools.agent_tool_base import AgentToolBase
from voice_agent_conversation.managers.agent_tools.restaurant_tools.booking_answers.booking_answer_mapping import BookingAnswerMapping, BookingSummary
from voice_agent_restaurant import DomainFacade as RestaurantDomainFacade, GuestDetailsReference, Reservation, ReservationCancellationRequest


@final
class CancelBookingByDetailsInput(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    phone_number: str = Field(description="The phone number the booking was made with, digits as spoken.")
    guest_name: str = Field(description="The name the booking is under, as the caller says it. The family name is enough.")
    booked_date: str = Field(description="The booking's date, as YYYY-MM-DD.")
    booked_time: str = Field(description="The booking's time, as 24-hour HH:MM.")


@final
class AgentToolCancelBookingByDetails(AgentToolBase[CancelBookingByDetailsInput, BookingSummary]):
    def __init__(self, restaurant_domain_facade: RestaurantDomainFacade) -> None:
        self._restaurant_domain_facade: RestaurantDomainFacade = restaurant_domain_facade

    @property
    @override
    def name(self) -> str:
        return "cancel_booking_by_details"

    @property
    @override
    def description(self) -> str:
        return (
            "Cancels a booking the caller has no confirmation code for, found by the phone number, name, date and time it is "
            "booked under, as find_bookings gave them. Returns the date, time and party size that were cancelled. "
            "Only call it after the caller has confirmed they want to cancel."
        )

    @property
    @override
    def input_model(self) -> type[CancelBookingByDetailsInput]:
        return CancelBookingByDetailsInput

    @override
    async def run(self, tool_input: CancelBookingByDetailsInput) -> BookingSummary:
        cancelled_reservation: Reservation = await self._restaurant_domain_facade.cancel_reservation(
            ReservationCancellationRequest(
                booking_reference=GuestDetailsReference(
                    phone_number=tool_input.phone_number,
                    guest_name=tool_input.guest_name,
                    booked_date=tool_input.booked_date,
                    booked_time=tool_input.booked_time,
                )
            )
        )
        return BookingAnswerMapping.to_booking_summary(cancelled_reservation)
