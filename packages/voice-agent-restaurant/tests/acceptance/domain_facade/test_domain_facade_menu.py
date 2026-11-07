# Acceptance tests for menu search, dish lookup, and the consistency of the seeded diet and allergen data.
# Black-box through the DomainFacade against a real SQLite store seeded from the bundled seed files.

from pathlib import Path
from typing import Final

import pytest

from acceptance_support.asserters.asserter_dish import AsserterDish
from acceptance_support.asserters.asserter_exception import AsserterException
from acceptance_support.service_locator_testing import create_domain_facade
from voice_agent_restaurant import (
    Allergen,
    DietLabel,
    Dish,
    DishLookupRequest,
    DishLookupValidationException,
    DishNotFoundException,
    MenuSearchRequest,
    MenuSearchValidationException,
)

SEEDED_DISH_COUNT: Final[int] = 32
KETO_MAXIMUM_CARBOHYDRATE_GRAMS: Final[int] = 15
CARNIVORE_MAXIMUM_CARBOHYDRATE_GRAMS: Final[int] = 5


def create_menu_search_request(
    diet_labels: list[str] | None = None,
    excluded_allergens: list[str] | None = None,
    category: str | None = None,
    maximum_calories: int | None = None,
    search_text: str | None = None,
) -> MenuSearchRequest:
    return MenuSearchRequest(
        diet_labels=diet_labels or [],
        excluded_allergens=excluded_allergens or [],
        category=category,
        maximum_calories=maximum_calories,
        search_text=search_text,
    )


class TestMenuSearch:
    async def test_SearchMenu_WhenNothingNarrowsTheSearch_ThenEverySeededDishIsReturned(self, restaurant_database_path: Path) -> None:
        async with create_domain_facade(restaurant_database_path) as domain_facade:
            dishes: list[Dish] = await domain_facade.search_menu(create_menu_search_request())

        assert len(dishes) == SEEDED_DISH_COUNT

    async def test_SearchMenu_WhenVeganWithoutSesameIsRequested_ThenExactlyTheVeganDishesFreeOfSesameAreReturned(
        self, restaurant_database_path: Path
    ) -> None:
        expected_dish_ids: list[str] = [
            "green-goddess-salad",
            "thai-peanut-noodle-salad",
            "king-oyster-mushroom-steak",
            "smoky-jackfruit-tacos",
            "grilled-broccolini",
            "coconut-panna-cotta",
            "fresh-mint-lemonade",
        ]

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            dishes: list[Dish] = await domain_facade.search_menu(create_menu_search_request(diet_labels=["vegan"], excluded_allergens=["sesame"]))

        assert [dish.dish_id for dish in dishes] == expected_dish_ids

    async def test_SearchMenu_WhenKetoAndCarnivoreAreBothRequested_ThenOnlyDishesSuitingBothAreReturned(self, restaurant_database_path: Path) -> None:
        expected_dish_ids: list[str] = ["dry-aged-ribeye", "butchers-board", "beef-bone-broth"]

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            dishes: list[Dish] = await domain_facade.search_menu(create_menu_search_request(diet_labels=["keto", "carnivore"]))

        assert [dish.dish_id for dish in dishes] == expected_dish_ids

    async def test_SearchMenu_WhenLabelsArriveInSpokenForms_ThenTheyMatchTheirStoredForms(self, restaurant_database_path: Path) -> None:
        async with create_domain_facade(restaurant_database_path) as domain_facade:
            expected_dishes: list[Dish] = await domain_facade.search_menu(
                create_menu_search_request(diet_labels=["gluten_free"], excluded_allergens=["tree_nuts"], category="desserts")
            )
            spoken_form_dishes: list[Dish] = await domain_facade.search_menu(
                create_menu_search_request(diet_labels=[" Gluten-Free "], excluded_allergens=["Tree Nuts"], category="Desserts")
            )

        assert expected_dishes, "the stored-form search must find at least one dish for the comparison to mean anything"
        assert spoken_form_dishes == expected_dishes

    async def test_SearchMenu_WhenCategoryAndCalorieCeilingAreGiven_ThenOnlyDishesInThatCategoryAtOrUnderTheCeilingAreReturned(
        self, restaurant_database_path: Path
    ) -> None:
        maximum_calories: int = 600
        expected_dish_ids: list[str] = ["cedar-plank-salmon", "king-oyster-mushroom-steak", "smoky-jackfruit-tacos", "seared-sea-scallops"]

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            dishes: list[Dish] = await domain_facade.search_menu(create_menu_search_request(category="mains", maximum_calories=maximum_calories))

        assert [dish.dish_id for dish in dishes] == expected_dish_ids

    async def test_SearchMenu_WhenSearchTextNamesAnIngredient_ThenDishesContainingItAreReturned(self, restaurant_database_path: Path) -> None:
        expected_dish_ids: list[str] = ["ember-caesar"]

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            dishes: list[Dish] = await domain_facade.search_menu(create_menu_search_request(search_text="ANCHOVIES"))

        assert [dish.dish_id for dish in dishes] == expected_dish_ids

    async def test_SearchMenu_WhenUnknownLabelsAndABadCalorieCeilingArrive_ThenEveryProblemIsReportedTogether(
        self, restaurant_database_path: Path
    ) -> None:
        expected_problem_phrases: list[str] = ["'raw'", "'mustard'", "'brunch'", "'maximum_calories' must be at least 1"]

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            with pytest.raises(MenuSearchValidationException) as raised:
                await domain_facade.search_menu(
                    create_menu_search_request(diet_labels=["raw"], excluded_allergens=["mustard"], category="brunch", maximum_calories=0)
                )

        AsserterException.assert_validation_problems_are_as_expected(expected_problem_phrases=expected_problem_phrases, actual_exception=raised.value)


class TestDietAndAllergenConsistency:
    async def test_SearchMenu_WhenAllDishesAreListed_ThenFreeFromLabelsAgreeWithTheAllergens(self, restaurant_database_path: Path) -> None:
        expected_disagreeing_dish_ids: list[str] = []

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            dishes: list[Dish] = await domain_facade.search_menu(create_menu_search_request())

        disagreeing_dish_ids: list[str] = [
            dish.dish_id
            for dish in dishes
            if (DietLabel.DAIRY_FREE in dish.diet_labels) == (Allergen.MILK in dish.allergens)
            or (DietLabel.NUT_FREE in dish.diet_labels) == (Allergen.TREE_NUTS in dish.allergens or Allergen.PEANUTS in dish.allergens)
            or (DietLabel.GLUTEN_FREE in dish.diet_labels and Allergen.WHEAT in dish.allergens)
        ]
        assert disagreeing_dish_ids == expected_disagreeing_dish_ids

    async def test_SearchMenu_WhenAllDishesAreListed_ThenEveryLifestyleDietLabelIsConsistentWithTheRecipe(
        self, restaurant_database_path: Path
    ) -> None:
        expected_inconsistent_dishes: list[str] = []
        animal_allergens: set[Allergen] = {Allergen.MILK, Allergen.EGGS, Allergen.FISH, Allergen.SHELLFISH}
        seafood_allergens: set[Allergen] = {Allergen.FISH, Allergen.SHELLFISH}
        paleo_excluded_allergens: set[Allergen] = {Allergen.MILK, Allergen.WHEAT, Allergen.PEANUTS, Allergen.SOY}

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            dishes: list[Dish] = await domain_facade.search_menu(create_menu_search_request())

        inconsistent_dishes: list[str] = []
        for dish in dishes:
            diet_labels: list[DietLabel] = dish.diet_labels
            if DietLabel.VEGAN in diet_labels and (DietLabel.VEGETARIAN not in diet_labels or animal_allergens & set(dish.allergens)):
                inconsistent_dishes.append(f"{dish.dish_id}: vegan")
            if DietLabel.VEGETARIAN in diet_labels and (DietLabel.PESCATARIAN not in diet_labels or seafood_allergens & set(dish.allergens)):
                inconsistent_dishes.append(f"{dish.dish_id}: vegetarian")
            if DietLabel.KETO in diet_labels and dish.nutrition.carbohydrate_grams > KETO_MAXIMUM_CARBOHYDRATE_GRAMS:
                inconsistent_dishes.append(f"{dish.dish_id}: keto")
            if DietLabel.CARNIVORE in diet_labels and (
                DietLabel.VEGETARIAN in diet_labels or dish.nutrition.carbohydrate_grams > CARNIVORE_MAXIMUM_CARBOHYDRATE_GRAMS
            ):
                inconsistent_dishes.append(f"{dish.dish_id}: carnivore")
            if DietLabel.PALEO in diet_labels and (paleo_excluded_allergens & set(dish.allergens) or DietLabel.GLUTEN_FREE not in diet_labels):
                inconsistent_dishes.append(f"{dish.dish_id}: paleo")
        assert inconsistent_dishes == expected_inconsistent_dishes


class TestDishLookup:
    async def test_RetrieveDish_WhenTheFullNameIsGivenInAnyCase_ThenThatDishIsReturnedWithItsDerivedLabels(
        self, restaurant_database_path: Path
    ) -> None:
        async with create_domain_facade(restaurant_database_path) as domain_facade:
            dish: Dish = await domain_facade.retrieve_dish(DishLookupRequest(dish_name="dry-aged RIBEYE"))

        AsserterDish.assert_dish_and_its_labels_are_as_expected(
            expected_dish_id="dry-aged-ribeye",
            expected_allergens=[Allergen.MILK],
            expected_diet_labels=[DietLabel.KETO, DietLabel.CARNIVORE, DietLabel.GLUTEN_FREE, DietLabel.NUT_FREE],
            actual_dish=dish,
        )

    @pytest.mark.parametrize(
        ("spoken_dish_name", "expected_dish_id"),
        [
            ("salmon", "cedar-plank-salmon"),
            ("the ribeye", "dry-aged-ribeye"),
            ("your scallops", "seared-sea-scallops"),
        ],
    )
    async def test_RetrieveDish_WhenOnlyOneDishContainsTheSpokenWords_ThenThatDishIsReturned(
        self, restaurant_database_path: Path, spoken_dish_name: str, expected_dish_id: str
    ) -> None:
        async with create_domain_facade(restaurant_database_path) as domain_facade:
            dish: Dish = await domain_facade.retrieve_dish(DishLookupRequest(dish_name=spoken_dish_name))

        assert dish.dish_id == expected_dish_id

    async def test_RetrieveDish_WhenSeveralDishesContainTheSpokenWords_ThenTheRefusalNamesEachOfThem(self, restaurant_database_path: Path) -> None:
        expected_close_match_names: list[str] = ["Smoked Chicken Wings", "Half Roast Chicken"]

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            with pytest.raises(DishNotFoundException) as raised:
                await domain_facade.retrieve_dish(DishLookupRequest(dish_name="chicken"))

        AsserterException.assert_dish_not_found_refusal_is_as_expected(
            expected_close_match_names=expected_close_match_names, actual_exception=raised.value
        )

    async def test_RetrieveDish_WhenNothingResemblesTheName_ThenTheRefusalOffersNoMatches(self, restaurant_database_path: Path) -> None:
        expected_close_match_names: list[str] = []

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            with pytest.raises(DishNotFoundException) as raised:
                await domain_facade.retrieve_dish(DishLookupRequest(dish_name="lasagna"))

        AsserterException.assert_dish_not_found_refusal_is_as_expected(
            expected_close_match_names=expected_close_match_names, actual_exception=raised.value
        )

    async def test_RetrieveDish_WhenTheNameIsBlank_ThenTheLookupIsRefusedAsInvalid(self, restaurant_database_path: Path) -> None:
        expected_problem_phrases: list[str] = ["'dish_name' is required"]

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            with pytest.raises(DishLookupValidationException) as raised:
                await domain_facade.retrieve_dish(DishLookupRequest(dish_name="  "))

        AsserterException.assert_validation_problems_are_as_expected(expected_problem_phrases=expected_problem_phrases, actual_exception=raised.value)
