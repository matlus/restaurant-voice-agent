from collections.abc import Iterable
from typing import Final

from voice_agent_restaurant.managers.exceptions.menu_exceptions import DishLookupValidationException, MenuSearchValidationException
from voice_agent_restaurant.managers.models.menu_models import (
    Allergen,
    DietLabel,
    DishLookupRequest,
    MenuCategory,
    MenuSearchCriteria,
    MenuSearchRequest,
)


class ValidatorMenuRequests:
    """Front-door validation for menu searches and dish lookups.

    Labels arrive in spoken forms ("Gluten-Free", "tree nuts"), so each is put into its stored form
    ("gluten_free", "tree_nuts") before it is judged. A valid request comes back as typed values.
    """

    MAXIMUM_SEARCH_TEXT_LENGTH: Final[int] = 100
    MAXIMUM_DISH_NAME_LENGTH: Final[int] = 100

    @classmethod
    def validate_menu_search_request(cls, menu_search_request: MenuSearchRequest) -> MenuSearchCriteria:
        diet_label_texts: list[str] = cls._as_labels(menu_search_request.diet_labels)
        allergen_texts: list[str] = cls._as_labels(menu_search_request.excluded_allergens)
        category_texts: list[str] = cls._as_labels([] if menu_search_request.category is None else [menu_search_request.category])
        search_text: str | None = cls._as_provided(menu_search_request.search_text)
        validation_problems: list[str] = []
        validation_problems.extend(cls._collect_unknown_choice_problems("diet_labels", diet_label_texts, DietLabel))
        validation_problems.extend(cls._collect_unknown_choice_problems("excluded_allergens", allergen_texts, Allergen))
        validation_problems.extend(cls._collect_unknown_choice_problems("category", category_texts, MenuCategory))
        validation_problems.extend(cls._collect_maximum_calories_problems(menu_search_request.maximum_calories))
        validation_problems.extend(cls._collect_search_text_problems(search_text))
        if validation_problems:
            raise MenuSearchValidationException(validation_problems, {"MenuSearch.ProblemCount": len(validation_problems)})
        return MenuSearchCriteria(
            diet_labels=[DietLabel(diet_label_text) for diet_label_text in diet_label_texts],
            excluded_allergens=[Allergen(allergen_text) for allergen_text in allergen_texts],
            category=next((MenuCategory(category_text) for category_text in category_texts), None),
            maximum_calories=menu_search_request.maximum_calories,
            search_text=search_text,
        )

    @classmethod
    def validate_dish_lookup_request(cls, dish_lookup_request: DishLookupRequest) -> str:
        dish_name: str | None = cls._as_provided(dish_lookup_request.dish_name)
        validation_problems: list[str] = cls._collect_dish_name_problems(dish_name)
        if dish_name is None or validation_problems:
            raise DishLookupValidationException(validation_problems, {"DishLookup.ProblemCount": len(validation_problems)})
        return dish_name

    @staticmethod
    def _collect_unknown_choice_problems(
        field_name: str, provided_choice_texts: Iterable[str], choice_type: type[DietLabel | Allergen | MenuCategory]
    ) -> list[str]:
        known_choice_texts: list[str] = [choice.value for choice in choice_type]
        return [
            f"'{field_name}' value '{provided_choice_text}' is not recognized; the recognized values are {', '.join(known_choice_texts)}"
            for provided_choice_text in provided_choice_texts
            if provided_choice_text not in known_choice_texts
        ]

    @staticmethod
    def _collect_maximum_calories_problems(maximum_calories: int | None) -> list[str]:
        if maximum_calories is not None and maximum_calories < 1:
            return [f"'maximum_calories' must be at least 1 but was {maximum_calories}"]
        return []

    @classmethod
    def _collect_search_text_problems(cls, search_text: str | None) -> list[str]:
        if search_text is not None and len(search_text) > cls.MAXIMUM_SEARCH_TEXT_LENGTH:
            return [f"'search_text' must contain at most {cls.MAXIMUM_SEARCH_TEXT_LENGTH} characters"]
        return []

    @classmethod
    def _collect_dish_name_problems(cls, dish_name: str | None) -> list[str]:
        if dish_name is None:
            return ["'dish_name' is required but was not provided"]
        if len(dish_name) > cls.MAXIMUM_DISH_NAME_LENGTH:
            return [f"'dish_name' must contain at most {cls.MAXIMUM_DISH_NAME_LENGTH} characters"]
        return []

    @classmethod
    def _as_labels(cls, label_texts: Iterable[str]) -> list[str]:
        return [cls._as_label(label_text) for label_text in label_texts if cls._as_provided(label_text) is not None]

    @staticmethod
    def _as_label(label_text: str) -> str:
        return "_".join(label_text.strip().casefold().replace("-", " ").split())

    @staticmethod
    def _as_provided(field_value: str | None) -> str | None:
        if field_value is None or field_value.strip() == "":
            return None
        return field_value.strip()
