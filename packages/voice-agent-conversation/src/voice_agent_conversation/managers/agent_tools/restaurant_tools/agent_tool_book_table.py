from typing import ClassVar, final, override

from pydantic import BaseModel, ConfigDict, Field

from voice_agent_conversation.managers.agent_tools.agent_tool_base import AgentToolBase
from voice_agent_restaurant import DomainFacade as RestaurantDomainFacade, Reservation, ReservationRequest


@final
class BookTableInput(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    guest_name: str = Field(description="The name the booking is under.")
    phone_number: str = Field(description="The caller's 10-digit phone number, digits as spoken.")
    party_size: int = Field(description="How many people.")
    reservation_date: str = Field(description="The date, as YYYY-MM-DD.")
    reservation_time: str = Field(description="The time, as 24-hour HH:MM.")
    notes: str | None = Field(default=None, description="Anything the caller wants the restaurant to know, such as an occasion.")


@final
class AgentToolBookTable(AgentToolBase[BookTableInput, Reservation]):
    def __init__(self, restaurant_domain_facade: RestaurantDomainFacade) -> None:
        self._restaurant_domain_facade: RestaurantDomainFacade = restaurant_domain_facade

    @property
    @override
    def name(self) -> str:
        return "book_table"

    @property
    @override
    def description(self) -> str:
        return (
            "Books a table and returns the booking with its confirmation code. "
            "Only call it after the caller has said yes to the details you checked with them. "
            "If no table is free, nothing is booked and the answer lists other free times."
        )

    @property
    @override
    def input_model(self) -> type[BookTableInput]:
        return BookTableInput

    @override
    async def run(self, tool_input: BookTableInput) -> Reservation:
        return await self._restaurant_domain_facade.create_reservation(
            ReservationRequest(
                guest_name=tool_input.guest_name,
                phone_number=tool_input.phone_number,
                party_size=tool_input.party_size,
                reservation_date=tool_input.reservation_date,
                reservation_time=tool_input.reservation_time,
                notes=tool_input.notes,
            )
        )
