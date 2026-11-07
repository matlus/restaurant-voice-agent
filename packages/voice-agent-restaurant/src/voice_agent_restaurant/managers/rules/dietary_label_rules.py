from collections.abc import Sequence
from typing import Final

from voice_agent_restaurant.managers.models.menu_models import Allergen, DietLabel, Dish, DishRecord


class DietaryLabelRules:
    """Composes the menu's view of a dish. The free-from labels are derived from allergen data only, so a dish's
    free-from labels can never disagree with the allergens it lists, whatever its recipe labels say."""

    FREE_FROM_LABELS: Final[frozenset[DietLabel]] = frozenset({DietLabel.GLUTEN_FREE, DietLabel.DAIRY_FREE, DietLabel.NUT_FREE})

    @classmethod
    def to_dish(cls, dish_record: DishRecord) -> Dish:
        lifestyle_diet_labels: list[DietLabel] = [
            diet_label for diet_label in dish_record.recipe_diet_labels if diet_label not in cls.FREE_FROM_LABELS
        ]
        return Dish(
            dish_id=dish_record.dish_id,
            name=dish_record.name,
            category=dish_record.category,
            description=dish_record.description,
            price_cents=dish_record.price_cents,
            ingredients=dish_record.ingredients,
            allergens=dish_record.allergens,
            diet_labels=lifestyle_diet_labels + cls._derive_free_from_labels(dish_record.contains_gluten, dish_record.allergens),
            nutrition=dish_record.nutrition,
            cross_contact_note=dish_record.cross_contact_note,
        )

    @staticmethod
    def _derive_free_from_labels(contains_gluten: bool, allergens: Sequence[Allergen]) -> list[DietLabel]:  # noqa: FBT001 - a plain fact, not a mode switch
        free_from_labels: list[DietLabel] = []
        if not contains_gluten and Allergen.WHEAT not in allergens:
            free_from_labels.append(DietLabel.GLUTEN_FREE)
        if Allergen.MILK not in allergens:
            free_from_labels.append(DietLabel.DAIRY_FREE)
        if Allergen.TREE_NUTS not in allergens and Allergen.PEANUTS not in allergens:
            free_from_labels.append(DietLabel.NUT_FREE)
        return free_from_labels
