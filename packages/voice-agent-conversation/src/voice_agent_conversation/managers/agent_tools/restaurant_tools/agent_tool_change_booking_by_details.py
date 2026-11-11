from typing import ClassVar, final, override

from pydantic import BaseModel, ConfigDict, Field

from voice_agent_conversation.managers.agent_tools.agent_tool_base import AgentToolBase
from voice_agent_conversation.managers.agent_tools.restaurant_tools.booking_answers.booking_answer_mapping import BookingAnswerMapping, BookingSummary
from voice_agent_restaurant import DomainFacade as RestaurantDomainFacade, GuestDetailsReference, Reservation, ReservationChangeRequest


@final
class ChangeBookingByDetailsInput(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    phone_number: str = Field(description="The phone number the booking was made with, digits as spoken.")
    guest_name: str = Field(description="The name the booking is under, as the caller says it. The family name is enough.")
    booked_date: str = Field(description="The booking's current date, as YYYY-MM-DD.")
    booked_time: str = Field(description="The booking's current time, as 24-hour HH:MM.")
    reservation_date: str | None = Field(default=None, description="A new date, as YYYY-MM-DD. Leave out to keep the current date.")
    reservation_time: str | None = Field(default=None, description="A new time, as 24-hour HH:MM. Leave out to keep the current time.")
    party_size: int | None = Field(default=None, description="A new number of people. Leave out to keep it.")
    notes: str | None = Field(default=None, description="New notes for the restaurant. Leave out to keep the current notes.")


@final
class AgentToolChangeBookingByDetails(AgentToolBase[ChangeBookingByDetailsInput, BookingSummary]):
    def __init__(self, restaurant_domain_facade: RestaurantDomainFacade) -> None:
        self._restaurant_domain_facade: RestaurantDomainFacade = restaurant_domain_facade

    @property
    @override
    def name(self) -> str:
        return "change_booking_by_details"

    @property
    @override
    def description(self) -> str:
        return (
            "Changes the date, time, party size or notes of a booking the caller has no confirmation code for. The booking is "
            "found by the phone number, name, date and time it is booked under, as find_bookings gave them. Returns its new date, "
            "time and party size. Only call it after the caller has confirmed the change you read back. "
            "If no table is free at the new time, nothing changes and the answer lists other free times."
        )

    @property
    @override
    def input_model(self) -> type[ChangeBookingByDetailsInput]:
        return ChangeBookingByDetailsInput

    @override
    async def run(self, tool_input: ChangeBookingByDetailsInput) -> BookingSummary:
        changed_reservation: Reservation = await self._restaurant_domain_facade.change_reservation(
            ReservationChangeRequest(
                booking_reference=GuestDetailsReference(
                    phone_number=tool_input.phone_number,
                    guest_name=tool_input.guest_name,
                    booked_date=tool_input.booked_date,
                    booked_time=tool_input.booked_time,
                ),
                reservation_date=tool_input.reservation_date,
                reservation_time=tool_input.reservation_time,
                party_size=tool_input.party_size,
                notes=tool_input.notes,
            )
        )
        return BookingAnswerMapping.to_booking_summary(changed_reservation)
