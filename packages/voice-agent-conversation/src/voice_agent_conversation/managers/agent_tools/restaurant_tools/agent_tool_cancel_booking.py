from typing import ClassVar, final, override

from pydantic import BaseModel, ConfigDict, Field

from voice_agent_conversation.managers.agent_tools.agent_tool_base import AgentToolBase
from voice_agent_conversation.managers.agent_tools.restaurant_tools.booking_answers.booking_answer_mapping import BookingAnswerMapping, BookingSummary
from voice_agent_restaurant import ConfirmationCodeReference, DomainFacade as RestaurantDomainFacade, Reservation, ReservationCancellationRequest


@final
class CancelBookingInput(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    confirmation_code: str = Field(description="The booking's six-character confirmation code.")
    phone_number: str | None = Field(default=None, description="The phone number the booking was made with, if the caller gives it.")


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
            "Cancels a booking, found by its confirmation code, and returns the date, time and party size that were cancelled. "
            "If the caller does not have the code, use cancel_booking_by_details instead. "
            "Only call it after the caller has confirmed they want to cancel."
        )

    @property
    @override
    def input_model(self) -> type[CancelBookingInput]:
        return CancelBookingInput

    @override
    async def run(self, tool_input: CancelBookingInput) -> BookingSummary:
        cancelled_reservation: Reservation = await self._restaurant_domain_facade.cancel_reservation(
            ReservationCancellationRequest(
                booking_reference=ConfirmationCodeReference(confirmation_code=tool_input.confirmation_code, phone_number=tool_input.phone_number)
            )
        )
        return BookingAnswerMapping.to_booking_summary(cancelled_reservation)
