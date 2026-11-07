import asyncio
import json
import sqlite3
from datetime import date
from pathlib import Path
from typing import Final, cast

from voice_agent_restaurant.managers.clocks.clock_base import ClockBase
from voice_agent_restaurant.managers.data_managers.exception_translators.translator_restaurant_store_exceptions import (
    TranslatorRestaurantStoreExceptions,
)
from voice_agent_restaurant.managers.data_managers.store.restaurant_store_connector import RestaurantStoreConnector
from voice_agent_restaurant.managers.data_managers.store.store_value_conversion import from_minutes_after_midnight
from voice_agent_restaurant.managers.exceptions.restaurant_store_exceptions import RestaurantStoreContractViolationException
from voice_agent_restaurant.managers.models.menu_models import Allergen, DietLabel, DishRecord, MenuCategory, Nutrition
from voice_agent_restaurant.managers.models.restaurant_models import (
    ClosedWeekday,
    Closure,
    DiningTable,
    OpenWeekday,
    ReservationPolicy,
    RestaurantProfile,
    Weekday,
    WeekdayHours,
)


class DataManagerRestaurant:
    """Reads the restaurant's reference data: profile, hours, closures, tables and menu.

    Every method runs its blocking SQLite work on a worker thread. Nothing SQLite-shaped leaves this class.
    """

    _WEEKDAY_CONTEXT_KEY: Final[str] = "Restaurant.Weekday"

    def __init__(self, database_path: Path, clock: ClockBase) -> None:
        self._restaurant_store_connector: RestaurantStoreConnector = RestaurantStoreConnector(database_path, clock)

    async def get_restaurant_profile(self) -> RestaurantProfile:
        return await asyncio.to_thread(self._get_restaurant_profile_synchronously)

    async def get_weekly_hours(self) -> list[WeekdayHours]:
        return await asyncio.to_thread(self._get_weekly_hours_synchronously)

    async def retrieve_weekday_hours(self, weekday: Weekday) -> WeekdayHours:
        return await asyncio.to_thread(self._retrieve_weekday_hours_synchronously, weekday)

    async def find_closures_between(self, first_date: date, last_date: date) -> list[Closure]:
        return await asyncio.to_thread(self._find_closures_between_synchronously, first_date, last_date)

    async def get_dining_tables(self) -> list[DiningTable]:
        return await asyncio.to_thread(self._get_dining_tables_synchronously)

    async def get_dish_records(self) -> list[DishRecord]:
        return await asyncio.to_thread(self._get_dish_records_synchronously)

    def _get_restaurant_profile_synchronously(self) -> RestaurantProfile:
        try:
            with self._restaurant_store_connector.open_connection() as connection:
                restaurant_row: sqlite3.Row | None = connection.execute("SELECT * FROM restaurant WHERE restaurant_id = 1").fetchone()
        except (sqlite3.Error, OSError) as store_error:
            raise TranslatorRestaurantStoreExceptions.translate(store_error, "read the restaurant profile") from store_error
        if restaurant_row is None:
            raise RestaurantStoreContractViolationException(
                message="The restaurant store holds no restaurant row, though every seeded store has exactly one",
                contextual_data_by_name={"RestaurantStore.Table": "restaurant"},
            )
        return self._map_restaurant_profile_row(restaurant_row)

    def _get_weekly_hours_synchronously(self) -> list[WeekdayHours]:
        try:
            with self._restaurant_store_connector.open_connection() as connection:
                hours_rows: list[sqlite3.Row] = connection.execute(
                    "SELECT weekday_index, opens_at_minutes, closes_at_minutes FROM weekly_hours ORDER BY weekday_index"
                ).fetchall()
        except (sqlite3.Error, OSError) as store_error:
            raise TranslatorRestaurantStoreExceptions.translate(store_error, "read the weekly opening hours") from store_error
        return [self._map_weekday_hours_row(hours_row) for hours_row in hours_rows]

    def _retrieve_weekday_hours_synchronously(self, weekday: Weekday) -> WeekdayHours:
        weekday_index: int = list(Weekday).index(weekday)
        try:
            with self._restaurant_store_connector.open_connection() as connection:
                hours_row: sqlite3.Row | None = connection.execute(
                    "SELECT weekday_index, opens_at_minutes, closes_at_minutes FROM weekly_hours WHERE weekday_index = ?", (weekday_index,)
                ).fetchone()
        except (sqlite3.Error, OSError) as store_error:
            raise TranslatorRestaurantStoreExceptions.translate(
                store_error, "read the opening hours for a weekday", {self._WEEKDAY_CONTEXT_KEY: weekday.value}
            ) from store_error
        if hours_row is None:
            raise RestaurantStoreContractViolationException(
                message=f"The restaurant store holds no opening hours for {weekday.value}, though every seeded store lists each weekday",
                contextual_data_by_name={self._WEEKDAY_CONTEXT_KEY: weekday.value},
            )
        return self._map_weekday_hours_row(hours_row)

    def _find_closures_between_synchronously(self, first_date: date, last_date: date) -> list[Closure]:
        try:
            with self._restaurant_store_connector.open_connection() as connection:
                closure_rows: list[sqlite3.Row] = connection.execute(
                    "SELECT closed_on, reason FROM closures WHERE closed_on BETWEEN ? AND ? ORDER BY closed_on",
                    (first_date.isoformat(), last_date.isoformat()),
                ).fetchall()
        except (sqlite3.Error, OSError) as store_error:
            raise TranslatorRestaurantStoreExceptions.translate(
                store_error, "read the closure dates", {"Closure.FirstDate": first_date.isoformat(), "Closure.LastDate": last_date.isoformat()}
            ) from store_error
        return [Closure(closed_on=date.fromisoformat(closure_row["closed_on"]), reason=closure_row["reason"]) for closure_row in closure_rows]

    def _get_dining_tables_synchronously(self) -> list[DiningTable]:
        try:
            with self._restaurant_store_connector.open_connection() as connection:
                table_rows: list[sqlite3.Row] = connection.execute("SELECT table_id, seats, area FROM dining_tables ORDER BY table_id").fetchall()
        except (sqlite3.Error, OSError) as store_error:
            raise TranslatorRestaurantStoreExceptions.translate(store_error, "read the dining tables") from store_error
        return [DiningTable(table_id=table_row["table_id"], seats=table_row["seats"], area=table_row["area"]) for table_row in table_rows]

    def _get_dish_records_synchronously(self) -> list[DishRecord]:
        try:
            with self._restaurant_store_connector.open_connection() as connection:
                dish_rows: list[sqlite3.Row] = connection.execute("SELECT * FROM dishes ORDER BY menu_position").fetchall()
        except (sqlite3.Error, OSError) as store_error:
            raise TranslatorRestaurantStoreExceptions.translate(store_error, "read the menu") from store_error
        return [self._map_dish_row(dish_row) for dish_row in dish_rows]

    @staticmethod
    def _map_restaurant_profile_row(restaurant_row: sqlite3.Row) -> RestaurantProfile:
        return RestaurantProfile(
            name=restaurant_row["name"],
            tagline=restaurant_row["tagline"],
            description=restaurant_row["description"],
            street_address=restaurant_row["street_address"],
            city=restaurant_row["city"],
            state_or_region=restaurant_row["state_or_region"],
            postal_code=restaurant_row["postal_code"],
            phone_number=restaurant_row["phone_number"],
            time_zone=restaurant_row["time_zone"],
            house_notes=cast(list[str], json.loads(restaurant_row["house_notes_json"])),
            reservation_policy=ReservationPolicy(
                seating_duration_minutes=restaurant_row["seating_duration_minutes"],
                slot_interval_minutes=restaurant_row["slot_interval_minutes"],
                minimum_party_size=restaurant_row["minimum_party_size"],
                maximum_party_size=restaurant_row["maximum_party_size"],
                booking_window_days=restaurant_row["booking_window_days"],
                minimum_lead_time_minutes=restaurant_row["minimum_lead_time_minutes"],
                late_arrival_hold_minutes=restaurant_row["late_arrival_hold_minutes"],
                large_party_guidance=restaurant_row["large_party_guidance"],
            ),
        )

    @staticmethod
    def _map_weekday_hours_row(hours_row: sqlite3.Row) -> WeekdayHours:
        weekday: Weekday = list(Weekday)[int(hours_row["weekday_index"])]
        # The schema requires both times or neither, so one missing time means the restaurant does not open that day.
        if hours_row["opens_at_minutes"] is None or hours_row["closes_at_minutes"] is None:
            return ClosedWeekday(weekday=weekday)
        return OpenWeekday(
            weekday=weekday,
            opens_at=from_minutes_after_midnight(hours_row["opens_at_minutes"]),
            closes_at=from_minutes_after_midnight(hours_row["closes_at_minutes"]),
        )

    @staticmethod
    def _map_dish_row(dish_row: sqlite3.Row) -> DishRecord:
        return DishRecord(
            dish_id=dish_row["dish_id"],
            name=dish_row["name"],
            category=MenuCategory(dish_row["category"]),
            description=dish_row["description"],
            price_cents=dish_row["price_cents"],
            ingredients=cast(list[str], json.loads(dish_row["ingredients_json"])),
            allergens=[Allergen(allergen_text) for allergen_text in cast(list[str], json.loads(dish_row["allergens_json"]))],
            contains_gluten=bool(dish_row["contains_gluten"]),
            recipe_diet_labels=[DietLabel(diet_text) for diet_text in cast(list[str], json.loads(dish_row["recipe_diet_labels_json"]))],
            nutrition=Nutrition(
                calories=dish_row["calories"],
                protein_grams=dish_row["protein_grams"],
                carbohydrate_grams=dish_row["carbohydrate_grams"],
                fat_grams=dish_row["fat_grams"],
            ),
            cross_contact_note=dish_row["cross_contact_note"],
        )
