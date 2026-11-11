from dataclasses import dataclass
from typing import ClassVar, final, override

from pydantic import BaseModel, ConfigDict, Field

from voice_agent_conversation.managers.agent_tools.agent_tool_base import AgentToolBase
from voice_agent_restaurant import Dish, DishLookupRequest, DomainFacade as RestaurantDomainFacade, RestaurantProfile


@final
class DescribeDishInput(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    dish_name: str = Field(description="The dish as the caller named it, even partly, such as 'the ribeye'.")


@final
@dataclass(frozen=True)
class DishDescription:
    """What the agent reads about one dish: the dish, and the restaurant's own allergen notice, which the agent passes on
    whenever it answers about the dish's allergens or free-from diets."""

    dish: Dish
    allergen_notice: str


@final
class AgentToolDescribeDish(AgentToolBase[DescribeDishInput, DishDescription]):
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
            "Use it when the caller asks about a particular dish. If no single dish matches, the answer names the closest ones. "
            "The answer also carries the restaurant's allergen notice."
        )

    @property
    @override
    def input_model(self) -> type[DescribeDishInput]:
        return DescribeDishInput

    @override
    async def run(self, tool_input: DescribeDishInput) -> DishDescription:
        dish: Dish = await self._restaurant_domain_facade.retrieve_dish(DishLookupRequest(dish_name=tool_input.dish_name))
        restaurant_profile: RestaurantProfile = await self._restaurant_domain_facade.get_restaurant_profile()
        return DishDescription(dish=dish, allergen_notice=restaurant_profile.allergen_notice)
