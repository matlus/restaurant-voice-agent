from typing import ClassVar, final, override

from pydantic import BaseModel, ConfigDict, Field

from voice_agent_conversation.managers.agent_tools.agent_tool_base import AgentToolBase
from voice_agent_restaurant import DomainFacade as RestaurantDomainFacade, Reservation, ReservationSearchRequest


@final
class FindBookingsInput(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    phone_number: str = Field(description="The phone number the bookings were made with, digits as spoken.")


@final
class AgentToolFindBookings(AgentToolBase[FindBookingsInput, list[Reservation]]):
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
            "Lists the caller's upcoming bookings for a phone number, each with its confirmation code. "
            "Use it when the caller wants to check, change or cancel a booking but does not have the code."
        )

    @property
    @override
    def input_model(self) -> type[FindBookingsInput]:
        return FindBookingsInput

    @override
    async def run(self, tool_input: FindBookingsInput) -> list[Reservation]:
        return await self._restaurant_domain_facade.find_reservations(ReservationSearchRequest(phone_number=tool_input.phone_number))
