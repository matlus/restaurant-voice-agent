from dataclasses import dataclass
from enum import StrEnum


class Allergen(StrEnum):
    """The nine major food allergens named by US labeling law."""

    MILK = "milk"
    EGGS = "eggs"
    FISH = "fish"
    SHELLFISH = "shellfish"
    TREE_NUTS = "tree_nuts"
    PEANUTS = "peanuts"
    WHEAT = "wheat"
    SOY = "soy"
    SESAME = "sesame"


class DietLabel(StrEnum):
    """Every diet a dish can suit. The first six come from the recipe; the free-from three are derived from allergen data."""

    VEGAN = "vegan"
    VEGETARIAN = "vegetarian"
    PESCATARIAN = "pescatarian"
    KETO = "keto"
    CARNIVORE = "carnivore"
    PALEO = "paleo"
    GLUTEN_FREE = "gluten_free"
    DAIRY_FREE = "dairy_free"
    NUT_FREE = "nut_free"


class MenuCategory(StrEnum):
    STARTERS = "starters"
    GARDEN = "garden"
    MAINS = "mains"
    SIDES = "sides"
    DESSERTS = "desserts"
    DRINKS = "drinks"


@dataclass(frozen=True)
class Nutrition:
    calories: int
    protein_grams: int
    carbohydrate_grams: int
    fat_grams: int


@dataclass(frozen=True)
class DishRecord:
    """A dish as the restaurant store holds it: the recipe's own diet labels only, never the derived ones."""

    dish_id: str
    name: str
    category: MenuCategory
    description: str
    price_cents: int
    ingredients: list[str]
    allergens: list[Allergen]
    contains_gluten: bool
    recipe_diet_labels: list[DietLabel]
    nutrition: Nutrition
    cross_contact_note: str | None


@dataclass(frozen=True)
class Dish:
    """A dish as the menu presents it, with every diet label it suits, recipe and derived alike."""

    dish_id: str
    name: str
    category: MenuCategory
    description: str
    price_cents: int
    ingredients: list[str]
    allergens: list[Allergen]
    diet_labels: list[DietLabel]
    nutrition: Nutrition
    cross_contact_note: str | None


@dataclass(frozen=True)
class MenuSearchRequest:
    """A menu search exactly as it arrived. Every value is checked by the validator before use.

    diet_labels: the dish must suit every one. excluded_allergens: the dish must contain none.
    search_text: matched against dish names, descriptions and ingredients.
    """

    diet_labels: list[str]
    excluded_allergens: list[str]
    category: str | None
    maximum_calories: int | None
    search_text: str | None


@dataclass(frozen=True)
class DishLookupRequest:
    dish_name: str | None


@dataclass(frozen=True)
class MenuSearchCriteria:
    """A validated menu search, with every label in its stored form."""

    diet_labels: list[DietLabel]
    excluded_allergens: list[Allergen]
    category: MenuCategory | None
    maximum_calories: int | None
    search_text: str | None
