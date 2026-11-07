from collections.abc import Sequence

from voice_agent_restaurant import Allergen, DietLabel, Dish


class AsserterDish:
    @staticmethod
    def assert_dish_and_its_labels_are_as_expected(
        *, expected_dish_id: str, expected_allergens: Sequence[Allergen], expected_diet_labels: Sequence[DietLabel], actual_dish: Dish
    ) -> None:
        assertion_failures: list[str] = []
        if actual_dish.dish_id != expected_dish_id:
            assertion_failures.append(f"Dish id: expected {expected_dish_id!r}; actual {actual_dish.dish_id!r}.")
        if actual_dish.allergens != list(expected_allergens):
            assertion_failures.append(f"Allergens: expected {list(expected_allergens)!r}; actual {actual_dish.allergens!r}.")
        if actual_dish.diet_labels != list(expected_diet_labels):
            assertion_failures.append(f"Diet labels: expected {list(expected_diet_labels)!r}; actual {actual_dish.diet_labels!r}.")
        failure_report: str = "\n".join(assertion_failures)
        assert not failure_report, f"Dish assertions failed:\n{failure_report}"
