from voice_agent_restaurant.managers.models.menu_models import Dish, MenuSearchCriteria


class MenuSearchRules:
    """Whether a dish satisfies a menu search. Pure calculation; no store access."""

    @staticmethod
    def is_match(dish: Dish, menu_search_criteria: MenuSearchCriteria) -> bool:
        if not all(diet_label in dish.diet_labels for diet_label in menu_search_criteria.diet_labels):
            return False
        if any(allergen in dish.allergens for allergen in menu_search_criteria.excluded_allergens):
            return False
        if menu_search_criteria.category is not None and dish.category != menu_search_criteria.category:
            return False
        if menu_search_criteria.maximum_calories is not None and dish.nutrition.calories > menu_search_criteria.maximum_calories:
            return False
        if menu_search_criteria.search_text is not None:
            folded_search_text: str = menu_search_criteria.search_text.casefold()
            searchable_texts: list[str] = [dish.name, dish.description, *dish.ingredients]
            return any(folded_search_text in searchable_text.casefold() for searchable_text in searchable_texts)
        return True
