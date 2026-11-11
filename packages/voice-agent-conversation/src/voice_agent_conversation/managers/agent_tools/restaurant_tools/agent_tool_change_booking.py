from typing import ClassVar, final, override

from pydantic import BaseModel, ConfigDict, Field

from voice_agent_conversation.managers.agent_tools.agent_tool_base import AgentToolBase
from voice_agent_conversation.managers.agent_tools.restaurant_tools.booking_answers import BookingAnswerMapping, BookingSummary
from voice_agent_restaurant import DomainFacade as RestaurantDomainFacade, Reservation, ReservationChangeRequest


@final
class ChangeBookingInput(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    confirmation_code: str | None = Field(default=None, description="The booking's six-character confirmation code, if the caller has it.")
    phone_number: str | None = Field(default=None, description="Without the code: the phone number the booking was made with.")
    guest_name: str | None = Field(default=None, description="Without the code: the name the booking is under.")
    booked_date: str | None = Field(default=None, description="Without the code: the booking's current date, as YYYY-MM-DD.")
    booked_time: str | None = Field(default=None, description="Without the code: the booking's current time, as 24-hour HH:MM.")
    reservation_date: str | None = Field(default=None, description="A new date, as YYYY-MM-DD. Leave out to keep the current date.")
    reservation_time: str | None = Field(default=None, description="A new time, as 24-hour HH:MM. Leave out to keep the current time.")
    party_size: int | None = Field(default=None, description="A new number of people. Leave out to keep it.")
    notes: str | None = Field(default=None, description="New notes for the restaurant. Leave out to keep the current notes.")


@final
class AgentToolChangeBooking(AgentToolBase[ChangeBookingInput, BookingSummary]):
    def __init__(self, restaurant_domain_facade: RestaurantDomainFacade) -> None:
        self._restaurant_domain_facade: RestaurantDomainFacade = restaurant_domain_facade

    @property
    @override
    def name(self) -> str:
        return "change_booking"

    @property
    @override
    def description(self) -> str:
        return (
            "Changes the date, time, party size or notes of an existing booking and returns its new date, time and party size. "
            "Identify the booking by its confirmation code, or, without the code, by the phone number, name, current date and "
            "current time it is booked under. The booking keeps its confirmation code. "
            "Only call it after the caller has confirmed the change you read back. "
            "If no table is free at the new time, nothing changes and the answer lists other free times."
        )

    @property
    @override
    def input_model(self) -> type[ChangeBookingInput]:
        return ChangeBookingInput

    @override
    async def run(self, tool_input: ChangeBookingInput) -> BookingSummary:
        changed_reservation: Reservation = await self._restaurant_domain_facade.change_reservation(
            ReservationChangeRequest(
                confirmation_code=tool_input.confirmation_code,
                phone_number=tool_input.phone_number,
                guest_name=tool_input.guest_name,
                booked_date=tool_input.booked_date,
                booked_time=tool_input.booked_time,
                reservation_date=tool_input.reservation_date,
                reservation_time=tool_input.reservation_time,
                party_size=tool_input.party_size,
                notes=tool_input.notes,
            )
        )
        return BookingAnswerMapping.to_booking_summary(changed_reservation)
