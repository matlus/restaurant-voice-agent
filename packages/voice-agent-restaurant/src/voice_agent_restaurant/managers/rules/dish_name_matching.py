import difflib
from collections.abc import Sequence
from typing import Final

from voice_agent_restaurant.managers.models.menu_models import Dish


class DishNameMatching:
    """Resolves a spoken dish name to the dishes it could mean. Pure calculation; no store access."""

    MAXIMUM_SUGGESTED_NAMES: Final[int] = 4
    CLOSE_MATCH_CUTOFF: Final[float] = 0.5
    # Words a guest says around a dish name ("the ribeye", "your salmon") that never appear in the name itself.
    FILLER_WORDS: Final[frozenset[str]] = frozenset({"a", "an", "the", "your", "some", "that"})

    @classmethod
    def find_matching_dishes(cls, dishes: Sequence[Dish], requested_name: str) -> list[Dish]:
        """Every dish whose name or id is the requested name; failing that, every dish whose name contains each spoken word."""
        folded_requested_name: str = requested_name.casefold()
        exact_matches: list[Dish] = [dish for dish in dishes if folded_requested_name in (dish.name.casefold(), dish.dish_id.casefold())]
        if exact_matches:
            return exact_matches
        requested_words: list[str] = cls._get_significant_words(folded_requested_name)
        return [dish for dish in dishes if all(requested_word in dish.name.casefold() for requested_word in requested_words)]

    @classmethod
    def get_suggested_names(cls, dishes: Sequence[Dish], matching_dishes: Sequence[Dish], requested_name: str) -> list[str]:
        """The names to offer when no single dish matches: the several matching dishes, or else the names that sound closest."""
        if matching_dishes:
            return [matching_dish.name for matching_dish in matching_dishes][: cls.MAXIMUM_SUGGESTED_NAMES]
        display_names_by_folded_name: dict[str, str] = {dish.name.casefold(): dish.name for dish in dishes}
        close_folded_names: list[str] = difflib.get_close_matches(
            requested_name.casefold(), list(display_names_by_folded_name), n=cls.MAXIMUM_SUGGESTED_NAMES, cutoff=cls.CLOSE_MATCH_CUTOFF
        )
        return [display_names_by_folded_name[close_folded_name] for close_folded_name in close_folded_names]

    @classmethod
    def _get_significant_words(cls, folded_requested_name: str) -> list[str]:
        requested_words: list[str] = folded_requested_name.split()
        significant_words: list[str] = [requested_word for requested_word in requested_words if requested_word not in cls.FILLER_WORDS]
        return significant_words or requested_words
