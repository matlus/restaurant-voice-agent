# Acceptance tests for menu search, dish lookup, and the consistency of the seeded diet and allergen data.
# Black-box through the DomainFacade against a real SQLite store seeded from the bundled seed files. The dishes a
# search or lookup should find are derived from the bundled menu by the rule the scenario states.

import re
from collections.abc import Iterable
from enum import Enum, auto
from pathlib import Path
from typing import Final

import pytest

from acceptance_support.asserters.asserter_dish import AsserterDish
from acceptance_support.asserters.asserter_exception import AsserterException, ExpectedExceptionMetadata
from acceptance_support.bundled_seed import SeededDish, read_seeded_dishes
from acceptance_support.service_locator_testing import create_domain_facade
from voice_agent_restaurant import (
    Allergen,
    DietLabel,
    Dish,
    DishLookupRequest,
    DishLookupValidationException,
    DishNotFoundException,
    ExceptionAction,
    LogEventMenu,
    MenuCategory,
    MenuSearchRequest,
    MenuSearchResult,
    MenuSearchValidationException,
    Severity,
)

KETO_MAXIMUM_CARBOHYDRATE_GRAMS: Final[int] = 15
CARNIVORE_MAXIMUM_CARBOHYDRATE_GRAMS: Final[int] = 5
# Dish names join words with spaces or hyphens ("Dry-Aged Ribeye"), and a guest may say either.
DISH_NAME_WORD_SEPARATORS_PATTERN: Final[re.Pattern[str]] = re.compile(r"[\s-]+")
CUT_SHORT_WORD_LENGTH: Final[int] = 3
REQUESTED_DISH_NAME_CONTEXT_NAME: Final[str] = "Menu.RequestedDishName"
MATCHING_DISH_COUNT_CONTEXT_NAME: Final[str] = "Menu.MatchingDishCount"


class SpokenDishForm(Enum):
    """How a guest says a dish's name when they say only part of it."""

    LAST_WORD = auto()
    EVERY_WORD_WITH_THE_LAST_CUT_SHORT = auto()


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


def retrieve_pinned_dish[TDish: (Dish, SeededDish)](seeded_dishes: Iterable[TDish], pinned_dish_id: str) -> TDish:
    pinned_dishes: list[TDish] = [seeded_dish for seeded_dish in seeded_dishes if seeded_dish.dish_id == pinned_dish_id]
    assert len(pinned_dishes) == 1, f"The seeded menu must hold exactly one dish '{pinned_dish_id}'; found {len(pinned_dishes)}"
    return pinned_dishes[0]


def split_dish_name_into_words(dish_name: str) -> list[str]:
    return [dish_name_word for dish_name_word in DISH_NAME_WORD_SEPARATORS_PATTERN.split(dish_name.casefold()) if dish_name_word]


def find_seeded_dishes_named_by(seeded_dishes: Iterable[SeededDish], spoken_words: Iterable[str]) -> list[SeededDish]:
    spoken_word_list: list[str] = list(spoken_words)
    return [
        seeded_dish
        for seeded_dish in seeded_dishes
        if all(
            any(dish_name_word.startswith(spoken_word) for dish_name_word in split_dish_name_into_words(seeded_dish.name))
            for spoken_word in spoken_word_list
        )
    ]


def to_spoken_words(dish_name: str, spoken_dish_form: SpokenDishForm) -> list[str]:
    dish_name_words: list[str] = split_dish_name_into_words(dish_name)
    if spoken_dish_form is SpokenDishForm.LAST_WORD:
        return dish_name_words[-1:]
    return [*dish_name_words[:-1], dish_name_words[-1][:CUT_SHORT_WORD_LENGTH]]


class TestMenuSearch:
    async def test_SearchMenu_WhenNothingNarrowsTheSearch_ThenEverySeededDishIsReturned(self, restaurant_database_path: Path) -> None:
        expected_dish_ids: list[str] = [seeded_dish.dish_id for seeded_dish in read_seeded_dishes()]

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            actual_dishes: list[Dish] = (await domain_facade.search_menu(create_menu_search_request())).dishes

        assert [actual_dish.dish_id for actual_dish in actual_dishes] == expected_dish_ids

    async def test_SearchMenu_WhenVeganWithoutSesameIsRequested_ThenExactlyTheVeganDishesFreeOfSesameAreReturned(
        self, restaurant_database_path: Path
    ) -> None:
        expected_dish_ids: list[str] = [
            seeded_dish.dish_id
            for seeded_dish in read_seeded_dishes()
            if DietLabel.VEGAN.value in seeded_dish.diets and Allergen.SESAME.value not in seeded_dish.allergens
        ]

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            actual_dishes: list[Dish] = (
                await domain_facade.search_menu(create_menu_search_request(diet_labels=["vegan"], excluded_allergens=["sesame"]))
            ).dishes

        assert [actual_dish.dish_id for actual_dish in actual_dishes] == expected_dish_ids

    async def test_SearchMenu_WhenKetoAndCarnivoreAreBothRequested_ThenOnlyDishesSuitingBothAreReturned(self, restaurant_database_path: Path) -> None:
        expected_dish_ids: list[str] = [
            seeded_dish.dish_id
            for seeded_dish in read_seeded_dishes()
            if DietLabel.KETO.value in seeded_dish.diets and DietLabel.CARNIVORE.value in seeded_dish.diets
        ]

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            actual_dishes: list[Dish] = (await domain_facade.search_menu(create_menu_search_request(diet_labels=["keto", "carnivore"]))).dishes

        assert [actual_dish.dish_id for actual_dish in actual_dishes] == expected_dish_ids

    async def test_SearchMenu_WhenLabelsArriveInSpokenForms_ThenTheyMatchTheirStoredForms(self, restaurant_database_path: Path) -> None:
        # Gluten free is derived from the allergen data: no gluten in the recipe and no wheat among the allergens.
        expected_dish_ids: list[str] = [
            seeded_dish.dish_id
            for seeded_dish in read_seeded_dishes()
            if seeded_dish.category == MenuCategory.DESSERTS.value
            and not seeded_dish.contains_gluten
            and Allergen.WHEAT.value not in seeded_dish.allergens
            and Allergen.TREE_NUTS.value not in seeded_dish.allergens
        ]

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            actual_spoken_form_dishes: list[Dish] = (
                await domain_facade.search_menu(
                    create_menu_search_request(diet_labels=[" Gluten-Free "], excluded_allergens=["Tree Nuts"], category="Desserts")
                )
            ).dishes

        assert [dish.dish_id for dish in actual_spoken_form_dishes] == expected_dish_ids

    @pytest.mark.parametrize(
        ("menu_search_request", "expected_filters_on_allergens"),
        [
            pytest.param(create_menu_search_request(excluded_allergens=["sesame"]), True, id="an-allergen-is-excluded"),
            pytest.param(create_menu_search_request(diet_labels=[" Gluten-Free "]), True, id="a-free-from-diet-is-asked-for"),
            pytest.param(create_menu_search_request(diet_labels=["keto"], category="mains"), False, id="only-a-lifestyle-diet-is-asked-for"),
        ],
    )
    async def test_SearchMenu_WhenTheSearchIsOrIsNotAboutAllergies_ThenTheResultSaysWhetherTheAllergenNoticeApplies(
        self, restaurant_database_path: Path, menu_search_request: MenuSearchRequest, expected_filters_on_allergens: bool
    ) -> None:
        async with create_domain_facade(restaurant_database_path) as domain_facade:
            actual_menu_search_result: MenuSearchResult = await domain_facade.search_menu(menu_search_request)

        assert actual_menu_search_result.filters_on_allergens == expected_filters_on_allergens

    async def test_SearchMenu_WhenCategoryAndCalorieCeilingAreGiven_ThenOnlyDishesInThatCategoryAtOrUnderTheCeilingAreReturned(
        self, restaurant_database_path: Path
    ) -> None:
        maximum_calories: int = 600
        expected_dish_ids: list[str] = [
            seeded_dish.dish_id
            for seeded_dish in read_seeded_dishes()
            if seeded_dish.category == MenuCategory.MAINS.value and seeded_dish.calories <= maximum_calories
        ]

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            actual_dishes: list[Dish] = (
                await domain_facade.search_menu(create_menu_search_request(category="mains", maximum_calories=maximum_calories))
            ).dishes

        assert [actual_dish.dish_id for actual_dish in actual_dishes] == expected_dish_ids

    async def test_SearchMenu_WhenSearchTextNamesAnIngredient_ThenDishesContainingItAreReturned(self, restaurant_database_path: Path) -> None:
        search_text: str = "ANCHOVIES"
        expected_dish_ids: list[str] = [
            seeded_dish.dish_id
            for seeded_dish in read_seeded_dishes()
            if any(
                search_text.casefold() in seeded_text.casefold()
                for seeded_text in [seeded_dish.name, seeded_dish.description, *seeded_dish.ingredients]
            )
        ]

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            actual_dishes: list[Dish] = (await domain_facade.search_menu(create_menu_search_request(search_text=search_text))).dishes

        assert [actual_dish.dish_id for actual_dish in actual_dishes] == expected_dish_ids

    async def test_SearchMenu_WhenUnknownLabelsAndABadCalorieCeilingArrive_ThenEveryProblemIsReportedTogether(
        self, restaurant_database_path: Path
    ) -> None:
        unknown_diet_label: str = "raw"
        unknown_excluded_allergen: str = "mustard"
        unknown_category: str = "brunch"
        expected_problem_phrases: list[str] = [
            f"'{unknown_diet_label}'",
            f"'{unknown_excluded_allergen}'",
            f"'{unknown_category}'",
            "'maximum_calories' must be at least 1",
        ]
        expected_exception_metadata: ExpectedExceptionMetadata = ExpectedExceptionMetadata(
            http_status_code=400,
            exception_action=ExceptionAction.USER_ACTION_REQUIRED,
            reason="Menu search failed validation",
            severity=Severity.ERROR,
            log_event=LogEventMenu.MENU_SEARCH_REQUEST_VALIDATION_FAILED,
        )
        expected_contextual_data_by_name: dict[str, int] = {"MenuSearch.ProblemCount": len(expected_problem_phrases)}

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            with pytest.raises(MenuSearchValidationException) as raised:
                await domain_facade.search_menu(
                    create_menu_search_request(
                        diet_labels=[unknown_diet_label],
                        excluded_allergens=[unknown_excluded_allergen],
                        category=unknown_category,
                        maximum_calories=0,
                    )
                )

        AsserterException.assert_validation_problems_are_as_expected(
            expected_problem_phrases=expected_problem_phrases,
            expected_exception_metadata=expected_exception_metadata,
            expected_contextual_data_by_name=expected_contextual_data_by_name,
            actual_validation_exception=raised.value,
        )


class TestDietAndAllergenConsistency:
    async def test_SearchMenu_WhenAllDishesAreListed_ThenFreeFromLabelsAgreeWithTheAllergens(self, restaurant_database_path: Path) -> None:
        expected_disagreeing_dish_labels: list[str] = []

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            dishes: list[Dish] = (await domain_facade.search_menu(create_menu_search_request())).dishes

        actual_disagreeing_dish_labels: list[str] = []
        for dish in dishes:
            if (DietLabel.DAIRY_FREE in dish.diet_labels) == (Allergen.MILK in dish.allergens):
                actual_disagreeing_dish_labels.append(f"{dish.dish_id}: dairy_free")
            if (DietLabel.NUT_FREE in dish.diet_labels) == (Allergen.TREE_NUTS in dish.allergens or Allergen.PEANUTS in dish.allergens):
                actual_disagreeing_dish_labels.append(f"{dish.dish_id}: nut_free")
            if DietLabel.GLUTEN_FREE in dish.diet_labels and Allergen.WHEAT in dish.allergens:
                actual_disagreeing_dish_labels.append(f"{dish.dish_id}: gluten_free")
        assert actual_disagreeing_dish_labels == expected_disagreeing_dish_labels, (
            f"Every free-from label on the {len(dishes)} seeded dishes must agree with that dish's allergens; "
            f"{len(actual_disagreeing_dish_labels)} labels disagree:\n" + "\n".join(actual_disagreeing_dish_labels)
        )

    async def test_SearchMenu_WhenAllDishesAreListed_ThenEveryLifestyleDietLabelIsConsistentWithTheRecipe(
        self, restaurant_database_path: Path
    ) -> None:
        expected_inconsistent_dishes: list[str] = []
        animal_allergens: set[Allergen] = {Allergen.MILK, Allergen.EGGS, Allergen.FISH, Allergen.SHELLFISH}
        seafood_allergens: set[Allergen] = {Allergen.FISH, Allergen.SHELLFISH}
        paleo_excluded_allergens: set[Allergen] = {Allergen.MILK, Allergen.WHEAT, Allergen.PEANUTS, Allergen.SOY}

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            dishes: list[Dish] = (await domain_facade.search_menu(create_menu_search_request())).dishes

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
        assert actual_inconsistent_dishes == expected_inconsistent_dishes, (
            f"Every lifestyle diet label on the {len(dishes)} seeded dishes must agree with that dish's recipe; "
            f"{len(actual_inconsistent_dishes)} labels disagree:\n" + "\n".join(actual_inconsistent_dishes)
        )


class TestDishLookup:
    async def test_RetrieveDish_WhenTheFullNameIsGivenInAnyCase_ThenThatDishIsReturnedWithItsDerivedLabels(
        self, restaurant_database_path: Path
    ) -> None:
        pinned_dish_id: str = "dry-aged-ribeye"
        seeded_dishes: list[SeededDish] = read_seeded_dishes()
        full_name_words: list[str] = split_dish_name_into_words(retrieve_pinned_dish(seeded_dishes, pinned_dish_id).name)
        named_dish_ids: list[str] = [seeded_dish.dish_id for seeded_dish in find_seeded_dishes_named_by(seeded_dishes, full_name_words)]
        assert named_dish_ids == [pinned_dish_id], (
            f"This full-name lookup needs {full_name_words!r} to name only '{pinned_dish_id}', but the seeded menu names {named_dish_ids!r}; "
            "the seeded data no longer supports the scenario"
        )

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            pinned_dish: Dish = retrieve_pinned_dish((await domain_facade.search_menu(create_menu_search_request())).dishes, pinned_dish_id)
            actual_dish: Dish = await domain_facade.retrieve_dish(DishLookupRequest(dish_name=pinned_dish.name.swapcase()))

        AsserterDish.assert_dish_and_its_labels_are_as_expected(
            expected_dish_id=pinned_dish.dish_id,
            expected_allergens=pinned_dish.allergens,
            expected_diet_labels=pinned_dish.diet_labels,
            actual_dish=actual_dish,
        )

    @pytest.mark.parametrize(
        ("pinned_dish_id", "lead_in_words", "spoken_dish_form"),
        [
            ("cedar-plank-salmon", "", SpokenDishForm.LAST_WORD),
            ("dry-aged-ribeye", "the ", SpokenDishForm.LAST_WORD),
            ("seared-sea-scallops", "your ", SpokenDishForm.LAST_WORD),
            ("dry-aged-ribeye", "", SpokenDishForm.EVERY_WORD_WITH_THE_LAST_CUT_SHORT),
        ],
    )
    async def test_RetrieveDish_WhenOnlyOneDishContainsTheSpokenWords_ThenThatDishIsReturned(
        self, restaurant_database_path: Path, pinned_dish_id: str, lead_in_words: str, spoken_dish_form: SpokenDishForm
    ) -> None:
        seeded_dishes: list[SeededDish] = read_seeded_dishes()
        spoken_words: list[str] = to_spoken_words(retrieve_pinned_dish(seeded_dishes, pinned_dish_id).name, spoken_dish_form)
        named_dish_ids: list[str] = [seeded_dish.dish_id for seeded_dish in find_seeded_dishes_named_by(seeded_dishes, spoken_words)]
        assert named_dish_ids == [pinned_dish_id], (
            f"This single-match lookup needs {spoken_words!r} to name only '{pinned_dish_id}', but the seeded menu names {named_dish_ids!r}; "
            "the seeded data no longer supports the scenario"
        )
        spoken_dish_name: str = lead_in_words + " ".join(spoken_words)
        expected_dish_id: str = pinned_dish_id

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            actual_dish: Dish = await domain_facade.retrieve_dish(DishLookupRequest(dish_name=spoken_dish_name))

        assert actual_dish.dish_id == expected_dish_id

    async def test_RetrieveDish_WhenSeveralDishesContainTheSpokenWords_ThenTheRefusalNamesEachOfThem(self, restaurant_database_path: Path) -> None:
        spoken_dish_name: str = "chicken"
        expected_close_match_names: list[str] = [
            seeded_dish.name for seeded_dish in find_seeded_dishes_named_by(read_seeded_dishes(), [spoken_dish_name])
        ]
        assert len(expected_close_match_names) > 1, (
            f"This several-match lookup needs more than one seeded dish named by '{spoken_dish_name}', but found {expected_close_match_names!r}; "
            "the seeded data no longer supports the scenario"
        )
        expected_message_phrases: list[str] = ["No single dish on the menu matches", f"'{spoken_dish_name}'"]
        expected_exception_metadata: ExpectedExceptionMetadata = ExpectedExceptionMetadata(
            http_status_code=404,
            exception_action=ExceptionAction.USER_ACTION_REQUIRED,
            reason="No single dish matches the name",
            severity=Severity.ERROR,
            log_event=LogEventMenu.DISH_LOOKUP,
        )
        expected_contextual_data_by_name: dict[str, str | int] = {
            REQUESTED_DISH_NAME_CONTEXT_NAME: spoken_dish_name,
            MATCHING_DISH_COUNT_CONTEXT_NAME: len(expected_close_match_names),
        }

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            with pytest.raises(DishNotFoundException) as raised:
                await domain_facade.retrieve_dish(DishLookupRequest(dish_name=spoken_dish_name))

        AsserterException.assert_dish_not_found_refusal_is_as_expected(
            expected_close_match_names=expected_close_match_names,
            expected_message_phrases=expected_message_phrases,
            expected_exception_metadata=expected_exception_metadata,
            expected_contextual_data_by_name=expected_contextual_data_by_name,
            actual_dish_not_found_exception=raised.value,
        )

    @pytest.mark.parametrize(
        "spoken_dish_name",
        [
            "lasagna",
            # "tea" sits inside "Steak", but no word on the menu starts with it, so the steak is never taken for tea.
            "the tea",
            # Separators alone hold no word to match, so they match no dish rather than every dish.
            "- -",
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
            log_event=LogEventMenu.DISH_LOOKUP,
        )
        expected_contextual_data_by_name: dict[str, str | int] = {
            REQUESTED_DISH_NAME_CONTEXT_NAME: spoken_dish_name,
            MATCHING_DISH_COUNT_CONTEXT_NAME: 0,
        }

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            with pytest.raises(DishNotFoundException) as raised:
                await domain_facade.retrieve_dish(DishLookupRequest(dish_name=spoken_dish_name))

        AsserterException.assert_dish_not_found_refusal_is_as_expected(
            expected_close_match_names=expected_close_match_names,
            expected_message_phrases=expected_message_phrases,
            expected_exception_metadata=expected_exception_metadata,
            expected_contextual_data_by_name=expected_contextual_data_by_name,
            actual_dish_not_found_exception=raised.value,
        )

    async def test_RetrieveDish_WhenTheNameIsBlank_ThenTheLookupIsRefusedAsInvalid(self, restaurant_database_path: Path) -> None:
        expected_problem_phrases: list[str] = ["'dish_name' is required"]
        expected_exception_metadata: ExpectedExceptionMetadata = ExpectedExceptionMetadata(
            http_status_code=400,
            exception_action=ExceptionAction.USER_ACTION_REQUIRED,
            reason="Dish lookup failed validation",
            severity=Severity.ERROR,
            log_event=LogEventMenu.DISH_LOOKUP_REQUEST_VALIDATION_FAILED,
        )
        expected_contextual_data_by_name: dict[str, int] = {"DishLookup.ProblemCount": len(expected_problem_phrases)}

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            with pytest.raises(DishLookupValidationException) as raised:
                await domain_facade.retrieve_dish(DishLookupRequest(dish_name="  "))

        AsserterException.assert_validation_problems_are_as_expected(
            expected_problem_phrases=expected_problem_phrases,
            expected_exception_metadata=expected_exception_metadata,
            expected_contextual_data_by_name=expected_contextual_data_by_name,
            actual_validation_exception=raised.value,
        )
