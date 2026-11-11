import json
import sqlite3
from dataclasses import dataclass
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
from voice_agent_restaurant.managers.models.store_models import StoreSeeding


@dataclass(frozen=True)
class _RestaurantReferenceData:
    """Everything about the restaurant that no request changes, read from the store in one go."""

    restaurant_profile: RestaurantProfile
    weekly_hours: list[WeekdayHours]
    closures: list[Closure]
    dining_tables: list[DiningTable]
    dish_records: list[DishRecord]


class DataManagerRestaurant:
    """Serves the restaurant's reference data: profile, hours, closures, tables and menu.

    No request changes this data, so it is read from the store once, when the data manager is built, and every
    method answers from that snapshot without touching the store. Building it creates and seeds a new store first,
    so a store that cannot be read fails at startup rather than on the first call. Nothing SQLite-shaped leaves
    this class.
    """

    _WEEKDAY_CONTEXT_KEY: Final[str] = "Restaurant.Weekday"
    _RESTAURANT_ROW_ID: Final[int] = 1

    def __init__(self, database_path: Path, store_seeding: StoreSeeding, clock: ClockBase) -> None:
        restaurant_store_connector: RestaurantStoreConnector = RestaurantStoreConnector(database_path, store_seeding, clock)
        self._restaurant_reference_data: _RestaurantReferenceData = self._read_reference_data(restaurant_store_connector)

    async def get_restaurant_profile(self) -> RestaurantProfile:
        return self._restaurant_reference_data.restaurant_profile

    async def get_weekly_hours(self) -> list[WeekdayHours]:
        return list(self._restaurant_reference_data.weekly_hours)

    async def retrieve_weekday_hours(self, weekday: Weekday) -> WeekdayHours:
        matching_weekday_hours: list[WeekdayHours] = [
            weekday_hours for weekday_hours in self._restaurant_reference_data.weekly_hours if weekday_hours.weekday == weekday
        ]
        if len(matching_weekday_hours) != 1:
            raise RestaurantStoreContractViolationException(
                message=(
                    f"The restaurant store holds no single set of opening hours for {weekday.value}, "
                    "though every seeded store lists each weekday once"
                ),
                contextual_data_by_name={self._WEEKDAY_CONTEXT_KEY: weekday.value, "Restaurant.MatchingWeekdayCount": len(matching_weekday_hours)},
            )
        return matching_weekday_hours[0]

    async def find_closures_between(self, first_date: date, last_date: date) -> list[Closure]:
        return [closure for closure in self._restaurant_reference_data.closures if first_date <= closure.closed_on <= last_date]

    async def get_dining_tables(self) -> list[DiningTable]:
        return list(self._restaurant_reference_data.dining_tables)

    async def get_dish_records(self) -> list[DishRecord]:
        return list(self._restaurant_reference_data.dish_records)

    @classmethod
    def _read_reference_data(cls, restaurant_store_connector: RestaurantStoreConnector) -> _RestaurantReferenceData:
        try:
            with restaurant_store_connector.open_connection() as connection:
                restaurant_row: sqlite3.Row | None = connection.execute(
                    "SELECT * FROM restaurant WHERE restaurant_id = ?", (cls._RESTAURANT_ROW_ID,)
                ).fetchone()
                hours_rows: list[sqlite3.Row] = connection.execute(
                    "SELECT weekday_index, opens_at_minutes, closes_at_minutes FROM weekly_hours ORDER BY weekday_index"
                ).fetchall()
                closure_rows: list[sqlite3.Row] = connection.execute("SELECT closed_on, reason FROM closures ORDER BY closed_on").fetchall()
                table_rows: list[sqlite3.Row] = connection.execute("SELECT table_id, seats, area FROM dining_tables ORDER BY table_id").fetchall()
                dish_rows: list[sqlite3.Row] = connection.execute("SELECT * FROM dishes ORDER BY menu_position").fetchall()
        except (sqlite3.Error, OSError) as store_error:
            raise TranslatorRestaurantStoreExceptions.translate(store_error, "read the restaurant's reference data") from store_error
        if restaurant_row is None:
            raise RestaurantStoreContractViolationException(
                message="The restaurant store holds no restaurant row, though every seeded store has exactly one",
                contextual_data_by_name={"RestaurantStore.Table": "restaurant"},
            )
        return _RestaurantReferenceData(
            restaurant_profile=cls._map_restaurant_profile_row(restaurant_row),
            weekly_hours=[cls._map_weekday_hours_row(hours_row) for hours_row in hours_rows],
            closures=[Closure(closed_on=date.fromisoformat(closure_row["closed_on"]), reason=closure_row["reason"]) for closure_row in closure_rows],
            dining_tables=[DiningTable(table_id=table_row["table_id"], seats=table_row["seats"], area=table_row["area"]) for table_row in table_rows],
            dish_records=[cls._map_dish_row(dish_row) for dish_row in dish_rows],
        )

    @classmethod
    def _map_restaurant_profile_row(cls, restaurant_row: sqlite3.Row) -> RestaurantProfile:
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
            allergen_notice=restaurant_row["allergen_notice"],
            house_notes=cls._decode_text_list_column(restaurant_row, "restaurant", "house_notes_json"),
            reservation_policy=ReservationPolicy(
                seating_duration_minutes=restaurant_row["seating_duration_minutes"],
                slot_interval_minutes=restaurant_row["slot_interval_minutes"],
                minimum_party_size=restaurant_row["minimum_party_size"],
                maximum_party_size=restaurant_row["maximum_party_size"],
                booking_window_days=restaurant_row["booking_window_days"],
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

    @classmethod
    def _map_dish_row(cls, dish_row: sqlite3.Row) -> DishRecord:
        return DishRecord(
            dish_id=dish_row["dish_id"],
            name=dish_row["name"],
            category=MenuCategory(dish_row["category"]),
            description=dish_row["description"],
            price_cents=dish_row["price_cents"],
            ingredients=cls._decode_text_list_column(dish_row, "dishes", "ingredients_json"),
            allergens=[Allergen(allergen_text) for allergen_text in cls._decode_text_list_column(dish_row, "dishes", "allergens_json")],
            contains_gluten=bool(dish_row["contains_gluten"]),
            recipe_diet_labels=[DietLabel(diet_text) for diet_text in cls._decode_text_list_column(dish_row, "dishes", "recipe_diet_labels_json")],
            nutrition=Nutrition(
                calories=dish_row["calories"],
                protein_grams=dish_row["protein_grams"],
                carbohydrate_grams=dish_row["carbohydrate_grams"],
                fat_grams=dish_row["fat_grams"],
            ),
            cross_contact_note=dish_row["cross_contact_note"],
        )

    @classmethod
    def _decode_text_list_column(cls, store_row: sqlite3.Row, table_name: str, column_name: str) -> list[str]:
        """Reads a column the store keeps as a JSON list of text. Anything else breaks the store's contract."""
        try:
            decoded_value: object = json.loads(store_row[column_name])
        except json.JSONDecodeError as decode_error:
            raise cls._create_unreadable_column_exception(table_name, column_name) from decode_error
        if not isinstance(decoded_value, list) or not all(isinstance(list_entry, str) for list_entry in cast(list[object], decoded_value)):
            raise cls._create_unreadable_column_exception(table_name, column_name)
        return cast(list[str], decoded_value)

    @staticmethod
    def _create_unreadable_column_exception(table_name: str, column_name: str) -> RestaurantStoreContractViolationException:
        return RestaurantStoreContractViolationException(
            message=f"The restaurant store's '{table_name}.{column_name}' column must hold a JSON list of text, but a row holds something else",
            contextual_data_by_name={"RestaurantStore.Table": table_name, "RestaurantStore.Column": column_name},
        )
