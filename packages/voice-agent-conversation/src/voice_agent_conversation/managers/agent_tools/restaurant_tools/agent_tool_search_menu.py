from typing import ClassVar, Final, cast, final, override

from pydantic import BaseModel, ConfigDict, Field, field_validator

from voice_agent_conversation.managers.agent_tools.agent_tool_base import AgentToolBase
from voice_agent_conversation.managers.agent_tools.restaurant_tools.spoken_answers.menu_answers import (
    AllergenMenuSearchAnswer,
    MenuAnswerMapping,
    MenuSearchAnswer,
)
from voice_agent_restaurant import (
    Allergen,
    DietLabel,
    DomainFacade as RestaurantDomainFacade,
    MenuCategory,
    MenuSearchRequest,
    MenuSearchResult,
    RestaurantProfile,
)


@final
class SearchMenuInput(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True, extra="forbid")

    # The enums put the allowed values in the schema the model reads; the validator below still accepts spoken variants.
    diet_labels: list[DietLabel] = Field(default_factory=list[DietLabel], description="Diets every dish must suit. Empty for any diet.")
    excluded_allergens: list[Allergen] = Field(default_factory=list[Allergen], description="Allergens no dish may contain. Empty for none.")
    category: MenuCategory | None = Field(default=None, description="Only dishes in this menu section.")
    maximum_calories: int | None = Field(default=None, description="Only dishes with at most this many calories.")
    search_text: str | None = Field(default=None, description="Words to find in dish names, descriptions or ingredients.")

    ENUMERATED_FIELD_NAMES: ClassVar[tuple[str, ...]] = ("diet_labels", "excluded_allergens", "category")
    WORD_SEPARATOR: ClassVar[Final[str]] = "_"

    @field_validator(*ENUMERATED_FIELD_NAMES, mode="before")
    @classmethod
    def _normalize_spoken_values(cls, field_value: object) -> object:
        """Turns 'Gluten-free' or 'tree nuts' into the enum value, as the restaurant's own search validation does."""
        if isinstance(field_value, str):
            return cls._normalize_spoken_value(field_value)
        if isinstance(field_value, list):
            return [
                cls._normalize_spoken_value(list_item) if isinstance(list_item, str) else list_item for list_item in cast(list[object], field_value)
            ]
        return field_value

    @classmethod
    def _normalize_spoken_value(cls, spoken_value: str) -> str:
        return cls.WORD_SEPARATOR.join(spoken_value.strip().casefold().replace("-", " ").split())


@final
class AgentToolSearchMenu(AgentToolBase[SearchMenuInput, MenuSearchAnswer | AllergenMenuSearchAnswer]):
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
            f"It lists at most {MenuAnswerMapping.MAXIMUM_LISTED_DISHES} dishes and says how many more match; describe_dish gives "
            "a dish's detail. A search that excludes allergens or asks for a free-from diet also returns the "
            "restaurant's allergen notice."
        )

    @property
    @override
    def input_model(self) -> type[SearchMenuInput]:
        return SearchMenuInput

    @override
    async def run(self, tool_input: SearchMenuInput) -> MenuSearchAnswer | AllergenMenuSearchAnswer:
        menu_search_result: MenuSearchResult = await self._restaurant_domain_facade.search_menu(
            MenuSearchRequest(
                diet_labels=list[str](tool_input.diet_labels),
                excluded_allergens=list[str](tool_input.excluded_allergens),
                category=tool_input.category,
                maximum_calories=tool_input.maximum_calories,
                search_text=tool_input.search_text,
            )
        )
        if not menu_search_result.filters_on_allergens:
            return MenuAnswerMapping.to_menu_search_answer(menu_search_result.dishes)
        restaurant_profile: RestaurantProfile = await self._restaurant_domain_facade.get_restaurant_profile()
        return MenuAnswerMapping.to_allergen_menu_search_answer(menu_search_result.dishes, restaurant_profile.allergen_notice)
