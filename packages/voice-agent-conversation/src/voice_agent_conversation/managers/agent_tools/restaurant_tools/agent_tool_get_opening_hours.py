from typing import ClassVar, final, override

from pydantic import BaseModel, ConfigDict

from voice_agent_conversation.managers.agent_tools.agent_tool_base import AgentToolBase
from voice_agent_conversation.managers.agent_tools.restaurant_tools.spoken_answers.schedule_answers import OpeningHoursAnswer, ScheduleAnswerMapping
from voice_agent_restaurant import DomainFacade as RestaurantDomainFacade, OpeningHours


@final
class GetOpeningHoursInput(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")


@final
class AgentToolGetOpeningHours(AgentToolBase[GetOpeningHoursInput, OpeningHoursAnswer]):
    def __init__(self, restaurant_domain_facade: RestaurantDomainFacade) -> None:
        self._restaurant_domain_facade: RestaurantDomainFacade = restaurant_domain_facade

    @property
    @override
    def name(self) -> str:
        return "get_opening_hours"

    @property
    @override
    def description(self) -> str:
        return (
            "Gives the hours for each weekday, the days the restaurant is closed, upcoming closures, "
            "and how long before closing the last table is seated."
        )

    @property
    @override
    def input_model(self) -> type[GetOpeningHoursInput]:
        return GetOpeningHoursInput

    @override
    async def run(self, tool_input: GetOpeningHoursInput) -> OpeningHoursAnswer:
        opening_hours: OpeningHours = await self._restaurant_domain_facade.get_opening_hours()
        return ScheduleAnswerMapping.to_opening_hours_answer(opening_hours)
