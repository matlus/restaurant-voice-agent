from typing import final, override

from voice_agent_restaurant.managers.exceptions.voice_agent_restaurant_exceptions import (
    ContextualDataDict,
    LogEventBase,
    VoiceAgentRestaurantBusinessBaseException,
)


class LogEventMenu(LogEventBase):
    MENU_SEARCH_REQUEST_VALIDATION_FAILED = "MenuSearchRequestValidationFailed"
    DISH_LOOKUP_REQUEST_VALIDATION_FAILED = "DishLookupRequestValidationFailed"
    DISH_LOOKUP = "DishLookup"


@final
class MenuSearchValidationException(VoiceAgentRestaurantBusinessBaseException):
    """Everything wrong with a menu search, reported together so the caller can correct it in one turn."""

    def __init__(self, validation_problems: list[str], contextual_data_by_name: ContextualDataDict | None = None) -> None:
        super().__init__(
            message=f"Menu search is invalid: {'; '.join(validation_problems)}",
            log_event=LogEventMenu.MENU_SEARCH_REQUEST_VALIDATION_FAILED,
            contextual_data_by_name=contextual_data_by_name,
        )
        self.validation_problems: list[str] = validation_problems

    @property
    @override
    def reason(self) -> str:
        return "Menu search failed validation"


@final
class DishLookupValidationException(VoiceAgentRestaurantBusinessBaseException):
    def __init__(self, validation_problems: list[str], contextual_data_by_name: ContextualDataDict | None = None) -> None:
        super().__init__(
            message=f"Dish lookup is invalid: {'; '.join(validation_problems)}",
            log_event=LogEventMenu.DISH_LOOKUP_REQUEST_VALIDATION_FAILED,
            contextual_data_by_name=contextual_data_by_name,
        )
        self.validation_problems: list[str] = validation_problems

    @property
    @override
    def reason(self) -> str:
        return "Dish lookup failed validation"


@final
class DishNotFoundException(VoiceAgentRestaurantBusinessBaseException):
    """No single dish matches the name. Close matches, when there are any, are named so the caller can pick one."""

    def __init__(self, dish_name: str, close_match_names: list[str], contextual_data_by_name: ContextualDataDict | None = None) -> None:
        close_matches_sentence: str = f" Did you mean one of these: {', '.join(close_match_names)}?" if close_match_names else ""
        super().__init__(
            message=f"No single dish on the menu matches '{dish_name}'.{close_matches_sentence}",
            log_event=LogEventMenu.DISH_LOOKUP,
            contextual_data_by_name=contextual_data_by_name,
        )
        self.dish_name: str = dish_name
        self.close_match_names: list[str] = close_match_names

    @property
    @override
    def reason(self) -> str:
        return "No single dish matches the name"

    @property
    @override
    def http_status_code(self) -> int:
        return 404
