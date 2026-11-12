from dataclasses import dataclass
from typing import Final, final

from voice_agent_conversation.managers.agent_tools.restaurant_tools.spoken_answers.spoken_forms import SpokenForms
from voice_agent_restaurant import Allergen, DietLabel, Dish, MenuCategory, Nutrition


@final
@dataclass(frozen=True)
class MenuDishListing:
    """One dish in a menu search: enough to mention it. describe_dish gives the rest."""

    name: str
    section: MenuCategory
    price: str
    diet_labels: list[DietLabel]


@final
@dataclass(frozen=True)
class MenuSearchAnswer:
    """What the agent reads for a menu search that is not about allergies, so it can offer more dishes or narrow the search."""

    dishes: list[MenuDishListing]
    unlisted_matching_dish_count: int


@final
@dataclass(frozen=True)
class AllergenMenuSearchAnswer:
    """What the agent reads for a menu search about allergies: the dishes, and the restaurant's own allergen notice, which
    the agent passes on because a dish free of an allergen by recipe can still carry traces of it."""

    dishes: list[MenuDishListing]
    unlisted_matching_dish_count: int
    allergen_notice: str


@final
@dataclass(frozen=True)
class DishDetails:
    name: str
    section: MenuCategory
    description: str
    price: str
    ingredients: list[str]
    allergens: list[Allergen]
    diet_labels: list[DietLabel]
    nutrition: Nutrition
    cross_contact_note: str | None


@final
@dataclass(frozen=True)
class DishDescription:
    """What the agent reads about one dish: the dish, and the restaurant's own allergen notice, which the agent passes on
    whenever it answers about the dish's allergens or free-from diets."""

    dish: DishDetails
    allergen_notice: str


@final
class MenuAnswerMapping:
    """Turns the restaurant's dishes into the answers the agent reads: short listings for a search, the detail for one dish."""

    # A caller can take in only a few dishes at once; the agent is told how many more there are.
    MAXIMUM_LISTED_DISHES: Final[int] = 8

    @classmethod
    def to_menu_search_answer(cls, dishes: list[Dish]) -> MenuSearchAnswer:
        return MenuSearchAnswer(dishes=cls._list_dishes(dishes), unlisted_matching_dish_count=cls._count_unlisted_dishes(dishes))

    @classmethod
    def to_allergen_menu_search_answer(cls, dishes: list[Dish], allergen_notice: str) -> AllergenMenuSearchAnswer:
        return AllergenMenuSearchAnswer(
            dishes=cls._list_dishes(dishes), unlisted_matching_dish_count=cls._count_unlisted_dishes(dishes), allergen_notice=allergen_notice
        )

    @staticmethod
    def to_dish_description(dish: Dish, allergen_notice: str) -> DishDescription:
        return DishDescription(
            dish=DishDetails(
                name=dish.name,
                section=dish.category,
                description=dish.description,
                price=SpokenForms.speak_price(dish.price_cents),
                ingredients=dish.ingredients,
                allergens=dish.allergens,
                diet_labels=dish.diet_labels,
                nutrition=dish.nutrition,
                cross_contact_note=dish.cross_contact_note,
            ),
            allergen_notice=allergen_notice,
        )

    @classmethod
    def _list_dishes(cls, dishes: list[Dish]) -> list[MenuDishListing]:
        return [
            MenuDishListing(name=dish.name, section=dish.category, price=SpokenForms.speak_price(dish.price_cents), diet_labels=dish.diet_labels)
            for dish in dishes[: cls.MAXIMUM_LISTED_DISHES]
        ]

    @classmethod
    def _count_unlisted_dishes(cls, dishes: list[Dish]) -> int:
        return max(len(dishes) - cls.MAXIMUM_LISTED_DISHES, 0)
