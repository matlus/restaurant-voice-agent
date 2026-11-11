from typing import ClassVar, final, override

from pydantic import BaseModel, ConfigDict, Field

from voice_agent_conversation.managers.agent_tools.agent_tool_base import AgentToolBase
from voice_agent_conversation.managers.agent_tools.restaurant_tools.booking_answers import BookingAnswerMapping, BookingSummary
from voice_agent_restaurant import DomainFacade as RestaurantDomainFacade, Reservation, ReservationCancellationRequest


@final
class CancelBookingInput(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    confirmation_code: str | None = Field(default=None, description="The booking's six-character confirmation code, if the caller has it.")
    phone_number: str | None = Field(default=None, description="Without the code: the phone number the booking was made with.")
    guest_name: str | None = Field(default=None, description="Without the code: the name the booking is under.")
    booked_date: str | None = Field(default=None, description="Without the code: the booking's date, as YYYY-MM-DD.")
    booked_time: str | None = Field(default=None, description="Without the code: the booking's time, as 24-hour HH:MM.")


@final
class AgentToolCancelBooking(AgentToolBase[CancelBookingInput, BookingSummary]):
    def __init__(self, restaurant_domain_facade: RestaurantDomainFacade) -> None:
        self._restaurant_domain_facade: RestaurantDomainFacade = restaurant_domain_facade

    @property
    @override
    def name(self) -> str:
        return "cancel_booking"

    @property
    @override
    def description(self) -> str:
        return (
            "Cancels a booking and returns the date, time and party size that were cancelled. "
            "Identify the booking by its confirmation code, or, without the code, by the phone number, name, date and time it "
            "is booked under. Only call it after the caller has confirmed they want to cancel."
        )

    @property
    @override
    def input_model(self) -> type[CancelBookingInput]:
        return CancelBookingInput

    @override
    async def run(self, tool_input: CancelBookingInput) -> BookingSummary:
        cancelled_reservation: Reservation = await self._restaurant_domain_facade.cancel_reservation(
            ReservationCancellationRequest(
                confirmation_code=tool_input.confirmation_code,
                phone_number=tool_input.phone_number,
                guest_name=tool_input.guest_name,
                booked_date=tool_input.booked_date,
                booked_time=tool_input.booked_time,
            )
        )
        return BookingAnswerMapping.to_booking_summary(cancelled_reservation)
