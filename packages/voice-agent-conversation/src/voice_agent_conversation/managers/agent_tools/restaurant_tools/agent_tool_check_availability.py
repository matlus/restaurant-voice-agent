from typing import ClassVar, final, override

from pydantic import BaseModel, ConfigDict, Field

from voice_agent_conversation.managers.agent_tools.agent_tool_base import AgentToolBase
from voice_agent_restaurant import AvailabilityRequest, AvailabilityResult, DomainFacade as RestaurantDomainFacade


@final
class CheckAvailabilityInput(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    reservation_date: str = Field(description="The date, as YYYY-MM-DD.")
    reservation_time: str = Field(description="The time, as 24-hour HH:MM.")
    party_size: int = Field(description="How many people.")
    confirmation_code: str | None = Field(
        default=None,
        description="When the caller asks about moving a booking they hold, its confirmation code, so that booking's own table counts as free.",
    )


@final
class AgentToolCheckAvailability(AgentToolBase[CheckAvailabilityInput, AvailabilityResult]):
    def __init__(self, restaurant_domain_facade: RestaurantDomainFacade) -> None:
        self._restaurant_domain_facade: RestaurantDomainFacade = restaurant_domain_facade

    @property
    @override
    def name(self) -> str:
        return "check_availability"

    @property
    @override
    def description(self) -> str:
        return (
            "Says whether a table for the party is free at the date and time. "
            "When it is not, the answer lists the nearest other times that day that are free. Books nothing. "
            "When the caller wants to move a booking, give its confirmation code so its own table is not counted as taken."
        )

    @property
    @override
    def input_model(self) -> type[CheckAvailabilityInput]:
        return CheckAvailabilityInput

    @override
    async def run(self, tool_input: CheckAvailabilityInput) -> AvailabilityResult:
        return await self._restaurant_domain_facade.check_availability(
            AvailabilityRequest(
                reservation_date=tool_input.reservation_date,
                reservation_time=tool_input.reservation_time,
                party_size=tool_input.party_size,
                confirmation_code=tool_input.confirmation_code,
            )
        )
