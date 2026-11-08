from typing import ClassVar, final, override

from pydantic import BaseModel, ConfigDict, Field

from voice_agent_conversation.managers.agent_tools.agent_tool_base import AgentToolBase
from voice_agent_restaurant import Dish, DishLookupRequest, DomainFacade as RestaurantDomainFacade


@final
class DescribeDishInput(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    dish_name: str = Field(description="The dish as the caller named it, even partly, such as 'the ribeye'.")


@final
class AgentToolDescribeDish(AgentToolBase[DescribeDishInput, Dish]):
    def __init__(self, restaurant_domain_facade: RestaurantDomainFacade) -> None:
        self._restaurant_domain_facade: RestaurantDomainFacade = restaurant_domain_facade

    @property
    @override
    def name(self) -> str:
        return "describe_dish"

    @property
    @override
    def description(self) -> str:
        return (
            "Gives everything about one dish: description, price in cents, ingredients, allergens, diets it suits and nutrition. "
            "Use it when the caller asks about a particular dish. If no single dish matches, the answer names the closest ones."
        )

    @property
    @override
    def input_model(self) -> type[DescribeDishInput]:
        return DescribeDishInput

    @override
    async def run(self, tool_input: DescribeDishInput) -> Dish:
        return await self._restaurant_domain_facade.retrieve_dish(DishLookupRequest(dish_name=tool_input.dish_name))
