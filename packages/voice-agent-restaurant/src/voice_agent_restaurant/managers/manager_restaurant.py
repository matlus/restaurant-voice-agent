from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from voice_agent_restaurant.managers.clocks.clock_base import ClockBase
from voice_agent_restaurant.managers.configuration_providers.settings_models.restaurant_store_settings import RestaurantStoreSettings
from voice_agent_restaurant.managers.data_managers.data_manager_restaurant import DataManagerRestaurant
from voice_agent_restaurant.managers.exceptions.menu_exceptions import DishNotFoundException
from voice_agent_restaurant.managers.models.menu_models import (
    Dish,
    DishLookupRequest,
    MenuSearchCriteria,
    MenuSearchRequest,
    MenuSearchResult,
)
from voice_agent_restaurant.managers.models.restaurant_models import Closure, OpeningHours, RestaurantProfile, WeekdayHours
from voice_agent_restaurant.managers.rules.dietary_label_rules import DietaryLabelRules
from voice_agent_restaurant.managers.rules.dish_name_matching import DishNameMatching
from voice_agent_restaurant.managers.rules.menu_search_rules import MenuSearchRules
from voice_agent_restaurant.managers.service_locators.service_locator_base import ServiceLocatorBase
from voice_agent_restaurant.managers.validators.validator_menu_requests import ValidatorMenuRequests


class ManagerRestaurant:
    """Answers questions about the restaurant itself: who it is, when it is open, and what is on the menu."""

    def __init__(self, service_locator: ServiceLocatorBase) -> None:
        self._clock: ClockBase = service_locator.create_clock()
        restaurant_store_settings: RestaurantStoreSettings = service_locator.get_configuration_provider().get_restaurant_store_settings()
        self._data_manager_restaurant: DataManagerRestaurant = DataManagerRestaurant(
            restaurant_store_settings.database_path, restaurant_store_settings.store_seeding, self._clock
        )

    async def get_restaurant_profile(self) -> RestaurantProfile:
        return await self._data_manager_restaurant.get_restaurant_profile()

    async def get_restaurant_local_now(self) -> datetime:
        restaurant_profile: RestaurantProfile = await self._data_manager_restaurant.get_restaurant_profile()
        return self._get_restaurant_now(restaurant_profile.time_zone)

    async def get_opening_hours(self) -> OpeningHours:
        restaurant_profile: RestaurantProfile = await self._data_manager_restaurant.get_restaurant_profile()
        restaurant_today: date = self._get_restaurant_now(restaurant_profile.time_zone).date()
        weekly_hours: list[WeekdayHours] = await self._data_manager_restaurant.get_weekly_hours()
        upcoming_closures: list[Closure] = await self._data_manager_restaurant.find_closures_between(
            restaurant_today, restaurant_today + timedelta(days=restaurant_profile.reservation_policy.booking_window_days)
        )
        return OpeningHours(
            weekly_hours=weekly_hours,
            upcoming_closures=upcoming_closures,
            last_seating_minutes_before_close=restaurant_profile.reservation_policy.seating_duration_minutes,
        )

    async def search_menu(self, menu_search_request: MenuSearchRequest) -> MenuSearchResult:
        menu_search_criteria: MenuSearchCriteria = ValidatorMenuRequests.validate_menu_search_request(menu_search_request)
        dishes: list[Dish] = await self._get_dishes()
        return MenuSearchResult(
            dishes=[dish for dish in dishes if MenuSearchRules.is_match(dish, menu_search_criteria)],
            filters_on_allergens=MenuSearchRules.filters_on_allergens(menu_search_criteria),
        )

    async def retrieve_dish(self, dish_lookup_request: DishLookupRequest) -> Dish:
        dish_name: str = ValidatorMenuRequests.validate_dish_lookup_request(dish_lookup_request)
        dishes: list[Dish] = await self._get_dishes()
        matching_dishes: list[Dish] = DishNameMatching.find_matching_dishes(dishes, dish_name)
        if len(matching_dishes) == 1:
            return matching_dishes[0]
        raise DishNotFoundException(
            dish_name=dish_name,
            close_match_names=DishNameMatching.find_suggested_names(dishes, matching_dishes, dish_name),
            contextual_data_by_name={"Menu.RequestedDishName": dish_name, "Menu.MatchingDishCount": len(matching_dishes)},
        )

    async def _get_dishes(self) -> list[Dish]:
        return [DietaryLabelRules.to_dish(dish_record) for dish_record in await self._data_manager_restaurant.get_dish_records()]

    def _get_restaurant_now(self, time_zone: str) -> datetime:
        return self._clock.now_utc().astimezone(ZoneInfo(time_zone))
