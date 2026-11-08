from typing import ClassVar, final, override

from pydantic import BaseModel, ConfigDict, Field

from voice_agent_conversation.managers.agent_tools.agent_tool_base import AgentToolBase
from voice_agent_restaurant import Allergen, DietLabel, Dish, DomainFacade as RestaurantDomainFacade, MenuCategory, MenuSearchRequest


@final
class SearchMenuInput(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    diet_labels: list[str] = Field(
        default_factory=list[str], description=f"Diets every dish must suit, each one of: {', '.join(DietLabel)}. Empty for any diet."
    )
    excluded_allergens: list[str] = Field(
        default_factory=list[str], description=f"Allergens no dish may contain, each one of: {', '.join(Allergen)}. Empty for none."
    )
    category: str | None = Field(default=None, description=f"Only dishes in this menu section, one of: {', '.join(MenuCategory)}.")
    maximum_calories: int | None = Field(default=None, description="Only dishes with at most this many calories.")
    search_text: str | None = Field(default=None, description="Words to find in dish names, descriptions or ingredients.")


@final
class AgentToolSearchMenu(AgentToolBase[SearchMenuInput, list[Dish]]):
    def __init__(self, restaurant_domain_facade: RestaurantDomainFacade) -> None:
        self._restaurant_domain_facade: RestaurantDomainFacade = restaurant_domain_facade

    @property
    @override
    def name(self) -> str:
        return "search_menu"

    @property
    @override
    def description(self) -> str:
        return (
            "Lists the dishes on the menu, optionally narrowed by diet, allergens to avoid, menu section, calories or words. "
            "Use it whenever the caller asks what there is to eat or drink, or what suits a diet or allergy. "
            "Prices are in cents."
        )

    @property
    @override
    def input_model(self) -> type[SearchMenuInput]:
        return SearchMenuInput

    @override
    async def run(self, tool_input: SearchMenuInput) -> list[Dish]:
        return await self._restaurant_domain_facade.search_menu(
            MenuSearchRequest(
                diet_labels=tool_input.diet_labels,
                excluded_allergens=tool_input.excluded_allergens,
                category=tool_input.category,
                maximum_calories=tool_input.maximum_calories,
                search_text=tool_input.search_text,
            )
        )
