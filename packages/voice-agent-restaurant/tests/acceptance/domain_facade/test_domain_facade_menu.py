# Acceptance tests for menu search, dish lookup, and the consistency of the seeded diet and allergen data.
# Black-box through the DomainFacade against a real SQLite store seeded from the bundled seed files.

from pathlib import Path
from typing import Final

import pytest

from acceptance_support.asserters.asserter_dish import AsserterDish
from acceptance_support.asserters.asserter_exception import AsserterException, ExpectedExceptionMetadata
from acceptance_support.bundled_seed import MENU_SEED_FILE_NAME, read_bundled_seed_file
from acceptance_support.service_locator_testing import create_domain_facade
from voice_agent_restaurant import (
    Allergen,
    DietLabel,
    Dish,
    DishLookupRequest,
    DishLookupValidationException,
    DishNotFoundException,
    ExceptionAction,
    MenuSearchRequest,
    MenuSearchValidationException,
    Severity,
)

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


def find_pinned_dish(seeded_dishes: list[Dish], pinned_dish_id: str) -> Dish:
    pinned_dishes: list[Dish] = [seeded_dish for seeded_dish in seeded_dishes if seeded_dish.dish_id == pinned_dish_id]
    assert len(pinned_dishes) == 1, f"The seeded menu must hold exactly one dish '{pinned_dish_id}'; found {len(pinned_dishes)}"
    return pinned_dishes[0]


class TestMenuSearch:
    async def test_SearchMenu_WhenNothingNarrowsTheSearch_ThenEverySeededDishIsReturned(self, restaurant_database_path: Path) -> None:
        expected_dish_count: int = len(read_bundled_seed_file(MENU_SEED_FILE_NAME)["dishes"])

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            actual_dishes: list[Dish] = await domain_facade.search_menu(create_menu_search_request())

        assert len(actual_dishes) == expected_dish_count

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
            actual_dishes: list[Dish] = await domain_facade.search_menu(
                create_menu_search_request(diet_labels=["vegan"], excluded_allergens=["sesame"])
            )

        assert [actual_dish.dish_id for actual_dish in actual_dishes] == expected_dish_ids

    async def test_SearchMenu_WhenKetoAndCarnivoreAreBothRequested_ThenOnlyDishesSuitingBothAreReturned(self, restaurant_database_path: Path) -> None:
        expected_dish_ids: list[str] = ["dry-aged-ribeye", "butchers-board", "beef-bone-broth"]

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            actual_dishes: list[Dish] = await domain_facade.search_menu(create_menu_search_request(diet_labels=["keto", "carnivore"]))

        assert [actual_dish.dish_id for actual_dish in actual_dishes] == expected_dish_ids

    async def test_SearchMenu_WhenLabelsArriveInSpokenForms_ThenTheyMatchTheirStoredForms(self, restaurant_database_path: Path) -> None:
        # The only seeded dessert that is gluten free and free of tree nuts.
        expected_dish_ids: list[str] = ["coconut-panna-cotta"]

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            actual_spoken_form_dishes: list[Dish] = await domain_facade.search_menu(
                create_menu_search_request(diet_labels=[" Gluten-Free "], excluded_allergens=["Tree Nuts"], category="Desserts")
            )

        assert [dish.dish_id for dish in actual_spoken_form_dishes] == expected_dish_ids

    async def test_SearchMenu_WhenCategoryAndCalorieCeilingAreGiven_ThenOnlyDishesInThatCategoryAtOrUnderTheCeilingAreReturned(
        self, restaurant_database_path: Path
    ) -> None:
        maximum_calories: int = 600
        expected_dish_ids: list[str] = ["cedar-plank-salmon", "king-oyster-mushroom-steak", "smoky-jackfruit-tacos", "seared-sea-scallops"]

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            actual_dishes: list[Dish] = await domain_facade.search_menu(
                create_menu_search_request(category="mains", maximum_calories=maximum_calories)
            )

        assert [actual_dish.dish_id for actual_dish in actual_dishes] == expected_dish_ids

    async def test_SearchMenu_WhenSearchTextNamesAnIngredient_ThenDishesContainingItAreReturned(self, restaurant_database_path: Path) -> None:
        expected_dish_ids: list[str] = ["ember-caesar"]

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            actual_dishes: list[Dish] = await domain_facade.search_menu(create_menu_search_request(search_text="ANCHOVIES"))

        assert [actual_dish.dish_id for actual_dish in actual_dishes] == expected_dish_ids

    async def test_SearchMenu_WhenUnknownLabelsAndABadCalorieCeilingArrive_ThenEveryProblemIsReportedTogether(
        self, restaurant_database_path: Path
    ) -> None:
        expected_problem_phrases: list[str] = ["'raw'", "'mustard'", "'brunch'", "'maximum_calories' must be at least 1"]
        expected_exception_metadata: ExpectedExceptionMetadata = ExpectedExceptionMetadata(
            http_status_code=400,
            exception_action=ExceptionAction.USER_ACTION_REQUIRED,
            reason="Menu search failed validation",
            severity=Severity.ERROR,
        )

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            with pytest.raises(MenuSearchValidationException) as raised:
                await domain_facade.search_menu(
                    create_menu_search_request(diet_labels=["raw"], excluded_allergens=["mustard"], category="brunch", maximum_calories=0)
                )

        AsserterException.assert_validation_problems_are_as_expected(
            expected_problem_phrases=expected_problem_phrases,
            expected_exception_metadata=expected_exception_metadata,
            actual_validation_exception=raised.value,
        )


class TestDietAndAllergenConsistency:
    async def test_SearchMenu_WhenAllDishesAreListed_ThenFreeFromLabelsAgreeWithTheAllergens(self, restaurant_database_path: Path) -> None:
        expected_disagreeing_dish_ids: list[str] = []

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            dishes: list[Dish] = await domain_facade.search_menu(create_menu_search_request())

        actual_disagreeing_dish_ids: list[str] = [
            dish.dish_id
            for dish in dishes
            if (DietLabel.DAIRY_FREE in dish.diet_labels) == (Allergen.MILK in dish.allergens)
            or (DietLabel.NUT_FREE in dish.diet_labels) == (Allergen.TREE_NUTS in dish.allergens or Allergen.PEANUTS in dish.allergens)
            or (DietLabel.GLUTEN_FREE in dish.diet_labels and Allergen.WHEAT in dish.allergens)
        ]
        assert actual_disagreeing_dish_ids == expected_disagreeing_dish_ids

    async def test_SearchMenu_WhenAllDishesAreListed_ThenEveryLifestyleDietLabelIsConsistentWithTheRecipe(
        self, restaurant_database_path: Path
    ) -> None:
        expected_inconsistent_dishes: list[str] = []
        animal_allergens: set[Allergen] = {Allergen.MILK, Allergen.EGGS, Allergen.FISH, Allergen.SHELLFISH}
        seafood_allergens: set[Allergen] = {Allergen.FISH, Allergen.SHELLFISH}
        paleo_excluded_allergens: set[Allergen] = {Allergen.MILK, Allergen.WHEAT, Allergen.PEANUTS, Allergen.SOY}

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            dishes: list[Dish] = await domain_facade.search_menu(create_menu_search_request())

        actual_inconsistent_dishes: list[str] = []
        for dish in dishes:
            diet_labels: list[DietLabel] = dish.diet_labels
            if DietLabel.VEGAN in diet_labels and (DietLabel.VEGETARIAN not in diet_labels or animal_allergens & set(dish.allergens)):
                actual_inconsistent_dishes.append(f"{dish.dish_id}: vegan")
            if DietLabel.VEGETARIAN in diet_labels and (DietLabel.PESCATARIAN not in diet_labels or seafood_allergens & set(dish.allergens)):
                actual_inconsistent_dishes.append(f"{dish.dish_id}: vegetarian")
            if DietLabel.KETO in diet_labels and dish.nutrition.carbohydrate_grams > KETO_MAXIMUM_CARBOHYDRATE_GRAMS:
                actual_inconsistent_dishes.append(f"{dish.dish_id}: keto")
            if DietLabel.CARNIVORE in diet_labels and (
                DietLabel.VEGETARIAN in diet_labels or dish.nutrition.carbohydrate_grams > CARNIVORE_MAXIMUM_CARBOHYDRATE_GRAMS
            ):
                actual_inconsistent_dishes.append(f"{dish.dish_id}: carnivore")
            if DietLabel.PALEO in diet_labels and (paleo_excluded_allergens & set(dish.allergens) or DietLabel.GLUTEN_FREE not in diet_labels):
                actual_inconsistent_dishes.append(f"{dish.dish_id}: paleo")
        assert actual_inconsistent_dishes == expected_inconsistent_dishes


class TestDishLookup:
    async def test_RetrieveDish_WhenTheFullNameIsGivenInAnyCase_ThenThatDishIsReturnedWithItsDerivedLabels(
        self, restaurant_database_path: Path
    ) -> None:
        pinned_dish_id: str = "dry-aged-ribeye"

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            pinned_dish: Dish = find_pinned_dish(await domain_facade.search_menu(create_menu_search_request()), pinned_dish_id)
            actual_dish: Dish = await domain_facade.retrieve_dish(DishLookupRequest(dish_name=pinned_dish.name.swapcase()))

        AsserterDish.assert_dish_and_its_labels_are_as_expected(
            expected_dish_id=pinned_dish.dish_id,
            expected_allergens=pinned_dish.allergens,
            expected_diet_labels=pinned_dish.diet_labels,
            actual_dish=actual_dish,
        )

    @pytest.mark.parametrize(
        ("spoken_dish_name", "expected_dish_id"),
        [
            ("salmon", "cedar-plank-salmon"),
            ("the ribeye", "dry-aged-ribeye"),
            ("your scallops", "seared-sea-scallops"),
            ("dry aged rib", "dry-aged-ribeye"),
        ],
    )
    async def test_RetrieveDish_WhenOnlyOneDishContainsTheSpokenWords_ThenThatDishIsReturned(
        self, restaurant_database_path: Path, spoken_dish_name: str, expected_dish_id: str
    ) -> None:
        async with create_domain_facade(restaurant_database_path) as domain_facade:
            actual_dish: Dish = await domain_facade.retrieve_dish(DishLookupRequest(dish_name=spoken_dish_name))

        assert actual_dish.dish_id == expected_dish_id

    async def test_RetrieveDish_WhenSeveralDishesContainTheSpokenWords_ThenTheRefusalNamesEachOfThem(self, restaurant_database_path: Path) -> None:
        spoken_dish_name: str = "chicken"
        expected_close_match_names: list[str] = ["Smoked Chicken Wings", "Half Roast Chicken"]
        expected_message_phrases: list[str] = ["No single dish on the menu matches", f"'{spoken_dish_name}'"]
        expected_exception_metadata: ExpectedExceptionMetadata = ExpectedExceptionMetadata(
            http_status_code=404,
            exception_action=ExceptionAction.USER_ACTION_REQUIRED,
            reason="No single dish matches the name",
            severity=Severity.ERROR,
        )

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            with pytest.raises(DishNotFoundException) as raised:
                await domain_facade.retrieve_dish(DishLookupRequest(dish_name=spoken_dish_name))

        AsserterException.assert_dish_not_found_refusal_is_as_expected(
            expected_close_match_names=expected_close_match_names,
            expected_message_phrases=expected_message_phrases,
            expected_exception_metadata=expected_exception_metadata,
            actual_dish_not_found_exception=raised.value,
        )

    @pytest.mark.parametrize(
        "spoken_dish_name",
        [
            "lasagna",
            # "tea" sits inside "Steak", but no word on the menu starts with it, so the steak is never taken for tea.
            "the tea",
        ],
    )
    async def test_RetrieveDish_WhenNoWordOnTheMenuStartsWithTheSpokenWords_ThenTheRefusalOffersNoMatches(
        self, restaurant_database_path: Path, spoken_dish_name: str
    ) -> None:
        expected_close_match_names: list[str] = []
        expected_message_phrases: list[str] = ["No single dish on the menu matches", f"'{spoken_dish_name}'"]
        expected_exception_metadata: ExpectedExceptionMetadata = ExpectedExceptionMetadata(
            http_status_code=404,
            exception_action=ExceptionAction.USER_ACTION_REQUIRED,
            reason="No single dish matches the name",
            severity=Severity.ERROR,
        )

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            with pytest.raises(DishNotFoundException) as raised:
                await domain_facade.retrieve_dish(DishLookupRequest(dish_name=spoken_dish_name))

        AsserterException.assert_dish_not_found_refusal_is_as_expected(
            expected_close_match_names=expected_close_match_names,
            expected_message_phrases=expected_message_phrases,
            expected_exception_metadata=expected_exception_metadata,
            actual_dish_not_found_exception=raised.value,
        )

    async def test_RetrieveDish_WhenTheNameIsBlank_ThenTheLookupIsRefusedAsInvalid(self, restaurant_database_path: Path) -> None:
        expected_problem_phrases: list[str] = ["'dish_name' is required"]
        expected_exception_metadata: ExpectedExceptionMetadata = ExpectedExceptionMetadata(
            http_status_code=400,
            exception_action=ExceptionAction.USER_ACTION_REQUIRED,
            reason="Dish lookup failed validation",
            severity=Severity.ERROR,
        )

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            with pytest.raises(DishLookupValidationException) as raised:
                await domain_facade.retrieve_dish(DishLookupRequest(dish_name="  "))

        AsserterException.assert_validation_problems_are_as_expected(
            expected_problem_phrases=expected_problem_phrases,
            expected_exception_metadata=expected_exception_metadata,
            actual_validation_exception=raised.value,
        )
