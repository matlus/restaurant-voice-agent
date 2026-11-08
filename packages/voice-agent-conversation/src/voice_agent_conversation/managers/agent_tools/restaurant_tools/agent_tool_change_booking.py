from typing import ClassVar, final, override

from pydantic import BaseModel, ConfigDict, Field

from voice_agent_conversation.managers.agent_tools.agent_tool_base import AgentToolBase
from voice_agent_restaurant import DomainFacade as RestaurantDomainFacade, Reservation, ReservationChangeRequest


@final
class ChangeBookingInput(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    confirmation_code: str = Field(description="The booking's six-character confirmation code.")
    phone_number: str | None = Field(default=None, description="The phone number the booking was made with, if the caller gives it.")
    reservation_date: str | None = Field(default=None, description="A new date, as YYYY-MM-DD. Leave out to keep the current date.")
    reservation_time: str | None = Field(default=None, description="A new time, as 24-hour HH:MM. Leave out to keep the current time.")
    party_size: int | None = Field(default=None, description="A new number of people. Leave out to keep it.")
    notes: str | None = Field(default=None, description="New notes for the restaurant. Leave out to keep the current notes.")


@final
class AgentToolChangeBooking(AgentToolBase[ChangeBookingInput, Reservation]):
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
            "Changes the date, time, party size or notes of an existing booking, found by its confirmation code, and returns it. "
            "If the caller does not have the code, get it with find_bookings first. "
            "Only call it after the caller has confirmed the change you read back. "
            "If no table is free at the new time, nothing changes and the answer lists other free times."
        )

    @property
    @override
    def input_model(self) -> type[ChangeBookingInput]:
        return ChangeBookingInput

    @override
    async def run(self, tool_input: ChangeBookingInput) -> Reservation:
        return await self._restaurant_domain_facade.change_reservation(
            ReservationChangeRequest(
                confirmation_code=tool_input.confirmation_code,
                phone_number=tool_input.phone_number,
                reservation_date=tool_input.reservation_date,
                reservation_time=tool_input.reservation_time,
                party_size=tool_input.party_size,
                notes=tool_input.notes,
            )
        )
