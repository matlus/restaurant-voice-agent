import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import time
from importlib import resources
from typing import Final

from voice_agent_restaurant.managers.data_managers.store.initialization.seed_data.seed_values.seed_file import JsonObject, JsonValue, SeedFile
from voice_agent_restaurant.managers.exceptions.restaurant_store_exceptions import RestaurantSeedDataInvalidException
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


@dataclass(frozen=True)
class SeedReservation:
    """An existing booking from the seed, placed on the next occurrence of its weekday when the store is created."""

    confirmation_code: str
    weekday: Weekday
    starts_at: time
    party_size: int
    table_id: str
    guest_name: str
    phone_number: str
    notes: str | None


@dataclass(frozen=True)
class RestaurantSeed:
    restaurant_profile: RestaurantProfile
    weekly_hours: list[WeekdayHours]
    closures: list[Closure]
    dining_tables: list[DiningTable]
    dish_records: list[DishRecord]
    seed_reservations: list[SeedReservation]


class SeedDataReader:
    RESTAURANT_FILE_NAME: Final[str] = "restaurant.json"
    TABLES_FILE_NAME: Final[str] = "tables.json"
    MENU_FILE_NAME: Final[str] = "menu.json"
    RESERVATIONS_FILE_NAME: Final[str] = "reservations.json"

    @classmethod
    def read_restaurant_seed(cls) -> RestaurantSeed:
        restaurant_seed_file: SeedFile = cls._load_seed_file(cls.RESTAURANT_FILE_NAME)
        tables_seed_file: SeedFile = cls._load_seed_file(cls.TABLES_FILE_NAME)
        menu_seed_file: SeedFile = cls._load_seed_file(cls.MENU_FILE_NAME)
        reservations_seed_file: SeedFile = cls._load_seed_file(cls.RESERVATIONS_FILE_NAME)
        restaurant_seed: RestaurantSeed = RestaurantSeed(
            restaurant_profile=cls._read_restaurant_profile(restaurant_seed_file),
            weekly_hours=cls._read_weekly_hours(restaurant_seed_file),
            closures=cls._read_closures(restaurant_seed_file),
            dining_tables=cls._read_dining_tables(tables_seed_file),
            dish_records=cls._read_dish_records(menu_seed_file),
            seed_reservations=cls._read_seed_reservations(reservations_seed_file),
        )
        cls._verify_unique_values(
            restaurant_seed_file, "$.closures", "closed_on", [closure.closed_on.isoformat() for closure in restaurant_seed.closures]
        )
        cls._verify_unique_values(tables_seed_file, "$.tables", "table_id", [dining_table.table_id for dining_table in restaurant_seed.dining_tables])
        cls._verify_unique_values(menu_seed_file, "$.dishes", "dish_id", [dish_record.dish_id for dish_record in restaurant_seed.dish_records])
        cls._verify_unique_values(
            reservations_seed_file,
            "$.reservations",
            "confirmation_code",
            [seed_reservation.confirmation_code for seed_reservation in restaurant_seed.seed_reservations],
        )
        cls._verify_reservation_tables(reservations_seed_file, restaurant_seed.seed_reservations, restaurant_seed.dining_tables)
        return restaurant_seed

    @staticmethod
    def _load_seed_file(file_name: str) -> SeedFile:
        seed_file_text: str = resources.files("voice_agent_restaurant").joinpath("seed_data", file_name).read_text(encoding="utf-8")
        try:
            root_value: JsonValue = json.loads(seed_file_text)
        except json.JSONDecodeError as json_error:
            raise RestaurantSeedDataInvalidException(
                message=f"Seed file '{file_name}' is not valid JSON: {json_error}",
                contextual_data_by_name={SeedFile.FILE_NAME_CONTEXT_KEY: file_name},
            ) from json_error
        if not isinstance(root_value, dict):
            raise RestaurantSeedDataInvalidException(
                message=f"Seed file '{file_name}' must hold a JSON object at its root",
                contextual_data_by_name={SeedFile.FILE_NAME_CONTEXT_KEY: file_name},
            )
        return SeedFile(file_name, root_value)

    @staticmethod
    def _read_restaurant_profile(restaurant_seed_file: SeedFile) -> RestaurantProfile:
        root_object: JsonObject = restaurant_seed_file.root_object
        reservation_policy_object: JsonObject = restaurant_seed_file.get_object(root_object, "reservation_policy", "$")
        reservation_policy_path: str = "$.reservation_policy"
        return RestaurantProfile(
            name=restaurant_seed_file.get_text(root_object, "name", "$"),
            tagline=restaurant_seed_file.get_text(root_object, "tagline", "$"),
            description=restaurant_seed_file.get_text(root_object, "description", "$"),
            street_address=restaurant_seed_file.get_text(root_object, "street_address", "$"),
            city=restaurant_seed_file.get_text(root_object, "city", "$"),
            state_or_region=restaurant_seed_file.get_text(root_object, "state_or_region", "$"),
            postal_code=restaurant_seed_file.get_text(root_object, "postal_code", "$"),
            phone_number=restaurant_seed_file.get_text(root_object, "phone_number", "$"),
            time_zone=restaurant_seed_file.get_time_zone_name(root_object, "time_zone", "$"),
            house_notes=restaurant_seed_file.get_texts(root_object, "house_notes", "$"),
            reservation_policy=ReservationPolicy(
                seating_duration_minutes=restaurant_seed_file.get_whole_number(
                    reservation_policy_object, "seating_duration_minutes", reservation_policy_path
                ),
                slot_interval_minutes=restaurant_seed_file.get_whole_number(
                    reservation_policy_object, "slot_interval_minutes", reservation_policy_path
                ),
                minimum_party_size=restaurant_seed_file.get_whole_number(reservation_policy_object, "minimum_party_size", reservation_policy_path),
                maximum_party_size=restaurant_seed_file.get_whole_number(reservation_policy_object, "maximum_party_size", reservation_policy_path),
                booking_window_days=restaurant_seed_file.get_whole_number(reservation_policy_object, "booking_window_days", reservation_policy_path),
                minimum_lead_time_minutes=restaurant_seed_file.get_whole_number(
                    reservation_policy_object, "minimum_lead_time_minutes", reservation_policy_path
                ),
                late_arrival_hold_minutes=restaurant_seed_file.get_whole_number(
                    reservation_policy_object, "late_arrival_hold_minutes", reservation_policy_path
                ),
                large_party_guidance=restaurant_seed_file.get_text(reservation_policy_object, "large_party_guidance", reservation_policy_path),
            ),
        )

    @classmethod
    def _read_weekly_hours(cls, restaurant_seed_file: SeedFile) -> list[WeekdayHours]:
        weekly_hours: list[WeekdayHours] = []
        position: int
        hours_object: JsonObject
        for position, hours_object in enumerate(restaurant_seed_file.get_objects(restaurant_seed_file.root_object, "weekly_hours", "$")):
            weekly_hours.append(cls._read_weekday_hours(restaurant_seed_file, hours_object, f"$.weekly_hours[{position}]"))
        if sorted(weekday_hours.weekday for weekday_hours in weekly_hours) != sorted(Weekday):
            raise restaurant_seed_file.fail("$.weekly_hours", "must list each weekday exactly once")
        return weekly_hours

    @staticmethod
    def _read_weekday_hours(restaurant_seed_file: SeedFile, hours_object: JsonObject, value_path: str) -> WeekdayHours:
        weekday: Weekday = restaurant_seed_file.get_choice(
            Weekday, restaurant_seed_file.get_text(hours_object, "weekday", value_path), f"{value_path}.weekday"
        )
        opens_at: time | None = restaurant_seed_file.get_optional_time(hours_object, "opens_at", value_path)
        closes_at: time | None = restaurant_seed_file.get_optional_time(hours_object, "closes_at", value_path)
        if opens_at is None and closes_at is None:
            return ClosedWeekday(weekday=weekday)
        if opens_at is None or closes_at is None:
            raise restaurant_seed_file.fail(value_path, "must give both 'opens_at' and 'closes_at', or neither on a day the restaurant does not open")
        return OpenWeekday(weekday=weekday, opens_at=opens_at, closes_at=closes_at)

    @staticmethod
    def _read_closures(restaurant_seed_file: SeedFile) -> list[Closure]:
        closures: list[Closure] = []
        position: int
        closure_object: JsonObject
        for position, closure_object in enumerate(restaurant_seed_file.get_objects(restaurant_seed_file.root_object, "closures", "$")):
            value_path: str = f"$.closures[{position}]"
            closures.append(
                Closure(
                    closed_on=restaurant_seed_file.get_date(closure_object, "closed_on", value_path),
                    reason=restaurant_seed_file.get_text(closure_object, "reason", value_path),
                )
            )
        return closures

    @staticmethod
    def _read_dining_tables(tables_seed_file: SeedFile) -> list[DiningTable]:
        dining_tables: list[DiningTable] = []
        position: int
        table_object: JsonObject
        for position, table_object in enumerate(tables_seed_file.get_objects(tables_seed_file.root_object, "tables", "$")):
            value_path: str = f"$.tables[{position}]"
            dining_tables.append(
                DiningTable(
                    table_id=tables_seed_file.get_text(table_object, "table_id", value_path),
                    seats=tables_seed_file.get_whole_number(table_object, "seats", value_path),
                    area=tables_seed_file.get_text(table_object, "area", value_path),
                )
            )
        return dining_tables

    @staticmethod
    def _read_dish_records(menu_seed_file: SeedFile) -> list[DishRecord]:
        dish_records: list[DishRecord] = []
        position: int
        dish_object: JsonObject
        for position, dish_object in enumerate(menu_seed_file.get_objects(menu_seed_file.root_object, "dishes", "$")):
            value_path: str = f"$.dishes[{position}]"
            nutrition_object: JsonObject = menu_seed_file.get_object(dish_object, "nutrition", value_path)
            nutrition_path: str = f"{value_path}.nutrition"
            dish_records.append(
                DishRecord(
                    dish_id=menu_seed_file.get_text(dish_object, "dish_id", value_path),
                    name=menu_seed_file.get_text(dish_object, "name", value_path),
                    category=menu_seed_file.get_choice(
                        MenuCategory, menu_seed_file.get_text(dish_object, "category", value_path), f"{value_path}.category"
                    ),
                    description=menu_seed_file.get_text(dish_object, "description", value_path),
                    price_cents=menu_seed_file.get_whole_number(dish_object, "price_cents", value_path),
                    ingredients=menu_seed_file.get_texts(dish_object, "ingredients", value_path),
                    allergens=[
                        menu_seed_file.get_choice(Allergen, allergen_text, f"{value_path}.allergens")
                        for allergen_text in menu_seed_file.get_texts(dish_object, "allergens", value_path)
                    ],
                    contains_gluten=menu_seed_file.get_flag(dish_object, "contains_gluten", value_path),
                    recipe_diet_labels=[
                        menu_seed_file.get_choice(DietLabel, diet_text, f"{value_path}.diets")
                        for diet_text in menu_seed_file.get_texts(dish_object, "diets", value_path)
                    ],
                    nutrition=Nutrition(
                        calories=menu_seed_file.get_whole_number(nutrition_object, "calories", nutrition_path),
                        protein_grams=menu_seed_file.get_whole_number(nutrition_object, "protein_grams", nutrition_path),
                        carbohydrate_grams=menu_seed_file.get_whole_number(nutrition_object, "carbohydrate_grams", nutrition_path),
                        fat_grams=menu_seed_file.get_whole_number(nutrition_object, "fat_grams", nutrition_path),
                    ),
                    cross_contact_note=menu_seed_file.get_optional_text(dish_object, "cross_contact_note", value_path),
                )
            )
        return dish_records

    @staticmethod
    def _read_seed_reservations(reservations_seed_file: SeedFile) -> list[SeedReservation]:
        seed_reservations: list[SeedReservation] = []
        position: int
        reservation_object: JsonObject
        for position, reservation_object in enumerate(reservations_seed_file.get_objects(reservations_seed_file.root_object, "reservations", "$")):
            value_path: str = f"$.reservations[{position}]"
            seed_reservations.append(
                SeedReservation(
                    confirmation_code=reservations_seed_file.get_text(reservation_object, "confirmation_code", value_path),
                    weekday=reservations_seed_file.get_choice(
                        Weekday, reservations_seed_file.get_text(reservation_object, "weekday", value_path), f"{value_path}.weekday"
                    ),
                    starts_at=reservations_seed_file.get_time(reservation_object, "starts_at", value_path),
                    party_size=reservations_seed_file.get_whole_number(reservation_object, "party_size", value_path),
                    table_id=reservations_seed_file.get_text(reservation_object, "table_id", value_path),
                    guest_name=reservations_seed_file.get_text(reservation_object, "guest_name", value_path),
                    phone_number=reservations_seed_file.get_text(reservation_object, "phone_number", value_path),
                    notes=reservations_seed_file.get_optional_text(reservation_object, "notes", value_path),
                )
            )
        return seed_reservations

    @staticmethod
    def _verify_unique_values(seed_file: SeedFile, list_path: str, key: str, values: Sequence[str]) -> None:
        seen_values: set[str] = set()
        position: int
        value: str
        for position, value in enumerate(values):
            if value in seen_values:
                raise seed_file.fail(f"{list_path}[{position}].{key}", f"repeats '{value}', which must be unique")
            seen_values.add(value)

    @staticmethod
    def _verify_reservation_tables(
        reservations_seed_file: SeedFile, seed_reservations: Sequence[SeedReservation], dining_tables: Sequence[DiningTable]
    ) -> None:
        seats_by_table_id: dict[str, int] = {dining_table.table_id: dining_table.seats for dining_table in dining_tables}
        position: int
        seed_reservation: SeedReservation
        for position, seed_reservation in enumerate(seed_reservations):
            table_path: str = f"$.reservations[{position}].table_id"
            if seed_reservation.table_id not in seats_by_table_id:
                raise reservations_seed_file.fail(table_path, f"names table '{seed_reservation.table_id}', which tables.json does not list")
            if seats_by_table_id[seed_reservation.table_id] < seed_reservation.party_size:
                raise reservations_seed_file.fail(
                    table_path, f"names table '{seed_reservation.table_id}', which is too small for a party of {seed_reservation.party_size}"
                )
