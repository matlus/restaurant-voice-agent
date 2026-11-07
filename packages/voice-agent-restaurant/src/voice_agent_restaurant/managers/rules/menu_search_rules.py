from collections.abc import Collection, Iterable

from voice_agent_restaurant.managers.models.menu_models import Allergen, DietLabel, Dish, MenuCategory, MenuSearchCriteria


class MenuSearchRules:
    """Whether a dish satisfies a menu search. Pure calculation; no store access."""

    @classmethod
    def is_match(cls, dish: Dish, menu_search_criteria: MenuSearchCriteria) -> bool:
        return (
            cls._has_requested_diet_labels(dish.diet_labels, menu_search_criteria.diet_labels)
            and cls._avoids_excluded_allergens(dish.allergens, menu_search_criteria.excluded_allergens)
            and cls._is_in_requested_category(dish.category, menu_search_criteria.category)
            and cls._is_within_calorie_limit(dish.nutrition.calories, menu_search_criteria.maximum_calories)
            and cls._contains_search_text(
                [dish.name, dish.description, *dish.ingredients],
                None if menu_search_criteria.search_text is None else menu_search_criteria.search_text.casefold(),
            )
        )

    @staticmethod
    def _has_requested_diet_labels(dish_diet_labels: Collection[DietLabel], requested_diet_labels: Iterable[DietLabel]) -> bool:
        return all(requested_diet_label in dish_diet_labels for requested_diet_label in requested_diet_labels)

    @staticmethod
    def _avoids_excluded_allergens(dish_allergens: Collection[Allergen], excluded_allergens: Iterable[Allergen]) -> bool:
        return not any(excluded_allergen in dish_allergens for excluded_allergen in excluded_allergens)

    @staticmethod
    def _is_in_requested_category(dish_category: MenuCategory, requested_category: MenuCategory | None) -> bool:
        return requested_category is None or dish_category == requested_category

    @staticmethod
    def _is_within_calorie_limit(dish_calories: int, maximum_calories: int | None) -> bool:
        return maximum_calories is None or dish_calories <= maximum_calories

    @staticmethod
    def _contains_search_text(dish_searchable_texts: Iterable[str], folded_search_text: str | None) -> bool:
        return folded_search_text is None or any(
            folded_search_text in dish_searchable_text.casefold() for dish_searchable_text in dish_searchable_texts
        )
