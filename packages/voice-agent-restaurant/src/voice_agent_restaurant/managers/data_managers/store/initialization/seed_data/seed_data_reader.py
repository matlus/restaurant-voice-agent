import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import time
from importlib import resources
from importlib.resources.abc import Traversable
from typing import Final

from voice_agent_restaurant.managers.data_managers.store.initialization.seed_data.seed_values.seed_file import JsonObject, JsonValue, SeedFile
from voice_agent_restaurant.managers.exceptions.restaurant_store_exceptions import RestaurantSeedDataInvalidException
from voice_agent_restaurant.managers.models.menu_models import Allergen, DietLabel, DishRecord, MenuCategory, Nutrition
from voice_agent_restaurant.managers.models.reservation_models import (
    CONFIRMATION_CODE_ALPHABET,
    CONFIRMATION_CODE_LENGTH,
    NATIONAL_PHONE_NUMBER_LENGTH,
    STORED_CONFIRMATION_CODE_PATTERN,
    STORED_PHONE_NUMBER_PATTERN,
)
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


@dataclass(frozen=True)
class _SeedFiles:
    restaurant_seed_file: SeedFile
    tables_seed_file: SeedFile
    menu_seed_file: SeedFile
    reservations_seed_file: SeedFile


class SeedDataReader:
    RESTAURANT_FILE_NAME: Final[str] = "restaurant.json"
    TABLES_FILE_NAME: Final[str] = "tables.json"
    MENU_FILE_NAME: Final[str] = "menu.json"
    RESERVATIONS_FILE_NAME: Final[str] = "reservations.json"
    CLOSED_ON_KEY: Final[str] = "closed_on"
    TABLE_ID_KEY: Final[str] = "table_id"
    DISH_ID_KEY: Final[str] = "dish_id"
    CONFIRMATION_CODE_KEY: Final[str] = "confirmation_code"
    PHONE_NUMBER_KEY: Final[str] = "phone_number"
    WEEKDAY_KEY: Final[str] = "weekday"
    MINUTES_PER_HOUR: Final[int] = 60

    @classmethod
    def read_restaurant_seed(cls, seed_directory: Traversable | None = None) -> RestaurantSeed:
        """Reads and checks the seed in seed_directory, which is the seed bundled with the package unless one is given."""
        source_directory: Traversable = resources.files("voice_agent_restaurant").joinpath("seed_data") if seed_directory is None else seed_directory
        seed_files: _SeedFiles = _SeedFiles(
            restaurant_seed_file=cls._load_seed_file(source_directory, cls.RESTAURANT_FILE_NAME),
            tables_seed_file=cls._load_seed_file(source_directory, cls.TABLES_FILE_NAME),
            menu_seed_file=cls._load_seed_file(source_directory, cls.MENU_FILE_NAME),
            reservations_seed_file=cls._load_seed_file(source_directory, cls.RESERVATIONS_FILE_NAME),
        )
        restaurant_seed: RestaurantSeed = RestaurantSeed(
            restaurant_profile=cls._read_restaurant_profile(seed_files.restaurant_seed_file),
            weekly_hours=cls._read_weekly_hours(seed_files.restaurant_seed_file),
            closures=cls._read_closures(seed_files.restaurant_seed_file),
            dining_tables=cls._read_dining_tables(seed_files.tables_seed_file),
            dish_records=cls._read_dish_records(seed_files.menu_seed_file),
            seed_reservations=cls._read_seed_reservations(seed_files.reservations_seed_file),
        )
        cls._verify_seed(restaurant_seed, seed_files)
        return restaurant_seed

    @staticmethod
    def _load_seed_file(seed_directory: Traversable, file_name: str) -> SeedFile:
        try:
            seed_file_text: str = seed_directory.joinpath(file_name).read_text(encoding="utf-8")
        # A file saved in another encoding cannot be decoded, which is as unusable as one that cannot be read.
        except (OSError, UnicodeDecodeError) as read_error:
            raise RestaurantSeedDataInvalidException(
                message=f"Seed file '{file_name}' cannot be read: {read_error}",
                contextual_data_by_name={SeedFile.FILE_NAME_CONTEXT_KEY: file_name},
            ) from read_error
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

    @classmethod
    def _read_restaurant_profile(cls, restaurant_seed_file: SeedFile) -> RestaurantProfile:
        root_object: JsonObject = restaurant_seed_file.root_object
        reservation_policy_object: JsonObject = restaurant_seed_file.get_object(root_object, "reservation_policy", "$")
        reservation_policy_path: str = "$.reservation_policy"
        reservation_policy: ReservationPolicy = ReservationPolicy(
            seating_duration_minutes=restaurant_seed_file.get_positive_number(
                reservation_policy_object, "seating_duration_minutes", reservation_policy_path
            ),
            slot_interval_minutes=restaurant_seed_file.get_positive_number(
                reservation_policy_object, "slot_interval_minutes", reservation_policy_path
            ),
            minimum_party_size=restaurant_seed_file.get_positive_number(reservation_policy_object, "minimum_party_size", reservation_policy_path),
            maximum_party_size=restaurant_seed_file.get_positive_number(reservation_policy_object, "maximum_party_size", reservation_policy_path),
            booking_window_days=restaurant_seed_file.get_non_negative_number(
                reservation_policy_object, "booking_window_days", reservation_policy_path
            ),
            late_arrival_hold_minutes=restaurant_seed_file.get_non_negative_number(
                reservation_policy_object, "late_arrival_hold_minutes", reservation_policy_path
            ),
            large_party_guidance=restaurant_seed_file.get_text(reservation_policy_object, "large_party_guidance", reservation_policy_path),
        )
        cls._verify_reservation_policy(restaurant_seed_file, reservation_policy, reservation_policy_path)
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
            reservation_policy=reservation_policy,
        )

    @classmethod
    def _read_weekly_hours(cls, restaurant_seed_file: SeedFile) -> list[WeekdayHours]:
        weekly_hours: list[WeekdayHours] = []
        position: int
        hours_object: JsonObject
        for position, hours_object in enumerate(restaurant_seed_file.get_objects(restaurant_seed_file.root_object, "weekly_hours", "$")):
            weekly_hours.append(cls._read_weekday_hours(restaurant_seed_file, hours_object, f"$.weekly_hours[{position}]"))
        cls._verify_every_weekday_listed_once(restaurant_seed_file, weekly_hours)
        return weekly_hours

    @staticmethod
    def _verify_every_weekday_listed_once(restaurant_seed_file: SeedFile, weekly_hours: Sequence[WeekdayHours]) -> None:
        if sorted(weekday_hours.weekday for weekday_hours in weekly_hours) == sorted(Weekday):
            return
        listed_weekdays: str = ", ".join(weekday_hours.weekday.value for weekday_hours in weekly_hours)
        permitted_weekdays: str = ", ".join(weekday.value for weekday in Weekday)
        raise restaurant_seed_file.fail("$.weekly_hours", f"must list each weekday exactly once ({permitted_weekdays}) but listed: {listed_weekdays}")

    @classmethod
    def _read_weekday_hours(cls, restaurant_seed_file: SeedFile, hours_object: JsonObject, value_path: str) -> WeekdayHours:
        weekday: Weekday = restaurant_seed_file.get_choice(
            Weekday, restaurant_seed_file.get_text(hours_object, cls.WEEKDAY_KEY, value_path), f"{value_path}.{cls.WEEKDAY_KEY}"
        )
        opens_at: time | None = restaurant_seed_file.get_optional_time(hours_object, "opens_at", value_path)
        closes_at: time | None = restaurant_seed_file.get_optional_time(hours_object, "closes_at", value_path)
        if opens_at is None and closes_at is None:
            return ClosedWeekday(weekday=weekday)
        if opens_at is None or closes_at is None:
            raise restaurant_seed_file.fail(value_path, "must give both 'opens_at' and 'closes_at', or neither on a day the restaurant does not open")
        # Seatings are kept as times of one calendar day, so service must end before midnight of the day it starts.
        if closes_at <= opens_at:
            raise restaurant_seed_file.fail(
                value_path,
                (
                    f"must have 'closes_at' later than 'opens_at' on the same day but opens at {opens_at:%H:%M} and closes at "
                    f"{closes_at:%H:%M}; service cannot run past midnight"
                ),
            )
        return OpenWeekday(weekday=weekday, opens_at=opens_at, closes_at=closes_at)

    @classmethod
    def _read_closures(cls, restaurant_seed_file: SeedFile) -> list[Closure]:
        closures: list[Closure] = []
        position: int
        closure_object: JsonObject
        for position, closure_object in enumerate(restaurant_seed_file.get_objects(restaurant_seed_file.root_object, "closures", "$")):
            value_path: str = f"$.closures[{position}]"
            closures.append(
                Closure(
                    closed_on=restaurant_seed_file.get_date(closure_object, cls.CLOSED_ON_KEY, value_path),
                    reason=restaurant_seed_file.get_text(closure_object, "reason", value_path),
                )
            )
        return closures

    @classmethod
    def _read_dining_tables(cls, tables_seed_file: SeedFile) -> list[DiningTable]:
        dining_tables: list[DiningTable] = []
        position: int
        table_object: JsonObject
        for position, table_object in enumerate(tables_seed_file.get_objects(tables_seed_file.root_object, "tables", "$")):
            value_path: str = f"$.tables[{position}]"
            dining_tables.append(
                DiningTable(
                    table_id=tables_seed_file.get_text(table_object, cls.TABLE_ID_KEY, value_path),
                    seats=tables_seed_file.get_positive_number(table_object, "seats", value_path),
                    area=tables_seed_file.get_text(table_object, "area", value_path),
                )
            )
        return dining_tables

    @classmethod
    def _read_dish_records(cls, menu_seed_file: SeedFile) -> list[DishRecord]:
        dish_records: list[DishRecord] = []
        position: int
        dish_object: JsonObject
        for position, dish_object in enumerate(menu_seed_file.get_objects(menu_seed_file.root_object, "dishes", "$")):
            value_path: str = f"$.dishes[{position}]"
            nutrition_object: JsonObject = menu_seed_file.get_object(dish_object, "nutrition", value_path)
            nutrition_path: str = f"{value_path}.nutrition"
            dish_records.append(
                DishRecord(
                    dish_id=menu_seed_file.get_text(dish_object, cls.DISH_ID_KEY, value_path),
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

    @classmethod
    def _read_seed_reservations(cls, reservations_seed_file: SeedFile) -> list[SeedReservation]:
        seed_reservations: list[SeedReservation] = []
        position: int
        reservation_object: JsonObject
        for position, reservation_object in enumerate(reservations_seed_file.get_objects(reservations_seed_file.root_object, "reservations", "$")):
            value_path: str = f"$.reservations[{position}]"
            seed_reservations.append(
                SeedReservation(
                    confirmation_code=cls._get_confirmation_code(reservations_seed_file, reservation_object, value_path),
                    weekday=reservations_seed_file.get_choice(
                        Weekday,
                        reservations_seed_file.get_text(reservation_object, cls.WEEKDAY_KEY, value_path),
                        f"{value_path}.{cls.WEEKDAY_KEY}",
                    ),
                    starts_at=reservations_seed_file.get_time(reservation_object, "starts_at", value_path),
                    party_size=reservations_seed_file.get_positive_number(reservation_object, "party_size", value_path),
                    table_id=reservations_seed_file.get_text(reservation_object, cls.TABLE_ID_KEY, value_path),
                    guest_name=reservations_seed_file.get_text(reservation_object, "guest_name", value_path),
                    phone_number=cls._get_phone_number(reservations_seed_file, reservation_object, value_path),
                    notes=reservations_seed_file.get_optional_text(reservation_object, "notes", value_path),
                )
            )
        return seed_reservations

    # Guests change and cancel a booking by its confirmation code, and may give its phone number, which the store matches
    # exactly in their stored form. A seed value in any other form could never be found.
    @classmethod
    def _get_confirmation_code(cls, reservations_seed_file: SeedFile, reservation_object: JsonObject, value_path: str) -> str:
        confirmation_code: str = reservations_seed_file.get_text(reservation_object, cls.CONFIRMATION_CODE_KEY, value_path)
        if STORED_CONFIRMATION_CODE_PATTERN.fullmatch(confirmation_code) is None:
            raise reservations_seed_file.fail(
                f"{value_path}.{cls.CONFIRMATION_CODE_KEY}",
                (
                    f"must be {CONFIRMATION_CODE_LENGTH} upper-case characters from '{CONFIRMATION_CODE_ALPHABET}', the form guests' codes "
                    f"are matched in, but was '{confirmation_code}'"
                ),
            )
        return confirmation_code

    @classmethod
    def _get_phone_number(cls, reservations_seed_file: SeedFile, reservation_object: JsonObject, value_path: str) -> str:
        phone_number: str = reservations_seed_file.get_text(reservation_object, cls.PHONE_NUMBER_KEY, value_path)
        if STORED_PHONE_NUMBER_PATTERN.fullmatch(phone_number) is None:
            raise reservations_seed_file.fail(
                f"{value_path}.{cls.PHONE_NUMBER_KEY}",
                (
                    f"must be a {NATIONAL_PHONE_NUMBER_LENGTH}-digit phone number written as digits alone, the form guests' numbers are "
                    f"matched in, but was '{phone_number}'"
                ),
            )
        return phone_number

    @classmethod
    def _verify_seed(cls, restaurant_seed: RestaurantSeed, seed_files: _SeedFiles) -> None:
        cls._verify_unique_values(
            seed_files.restaurant_seed_file,
            "$.closures",
            cls.CLOSED_ON_KEY,
            [closure.closed_on.isoformat() for closure in restaurant_seed.closures],
        )
        cls._verify_unique_values(
            seed_files.tables_seed_file, "$.tables", cls.TABLE_ID_KEY, [dining_table.table_id for dining_table in restaurant_seed.dining_tables]
        )
        cls._verify_unique_values(
            seed_files.menu_seed_file, "$.dishes", cls.DISH_ID_KEY, [dish_record.dish_id for dish_record in restaurant_seed.dish_records]
        )
        cls._verify_unique_values(
            seed_files.reservations_seed_file,
            "$.reservations",
            cls.CONFIRMATION_CODE_KEY,
            [seed_reservation.confirmation_code for seed_reservation in restaurant_seed.seed_reservations],
        )
        cls._verify_opening_times_on_slot_grid(
            seed_files.restaurant_seed_file, restaurant_seed.weekly_hours, restaurant_seed.restaurant_profile.reservation_policy.slot_interval_minutes
        )
        cls._verify_reservation_party_sizes(
            seed_files.reservations_seed_file, restaurant_seed.seed_reservations, restaurant_seed.restaurant_profile.reservation_policy
        )
        cls._verify_reservation_tables(seed_files.reservations_seed_file, restaurant_seed.seed_reservations, restaurant_seed.dining_tables)
        cls._verify_reservation_seating_times(seed_files.reservations_seed_file, restaurant_seed)

    @classmethod
    def _verify_reservation_policy(cls, restaurant_seed_file: SeedFile, reservation_policy: ReservationPolicy, reservation_policy_path: str) -> None:
        if reservation_policy.maximum_party_size < reservation_policy.minimum_party_size:
            raise restaurant_seed_file.fail(
                f"{reservation_policy_path}.maximum_party_size",
                f"must be at least the minimum_party_size of {reservation_policy.minimum_party_size} but was {reservation_policy.maximum_party_size}",
            )
        # Bookable times step from each day's opening time, while a requested time is judged by its minute of the hour.
        # The two agree only when the interval divides an hour and every opening time lies on that grid.
        if cls.MINUTES_PER_HOUR % reservation_policy.slot_interval_minutes != 0:
            raise restaurant_seed_file.fail(
                f"{reservation_policy_path}.slot_interval_minutes",
                (
                    "must divide an hour evenly, so bookable times fall on the same minutes every hour, "
                    f"but was {reservation_policy.slot_interval_minutes}"
                ),
            )

    @staticmethod
    def _verify_unique_values(seed_file: SeedFile, list_path: str, key: str, key_texts: Sequence[str]) -> None:
        seen_key_texts: set[str] = set()
        position: int
        key_text: str
        for position, key_text in enumerate(key_texts):
            if key_text in seen_key_texts:
                raise seed_file.fail(f"{list_path}[{position}].{key}", f"repeats '{key_text}', which must be unique")
            seen_key_texts.add(key_text)

    @classmethod
    def _verify_opening_times_on_slot_grid(
        cls, restaurant_seed_file: SeedFile, weekly_hours: Sequence[WeekdayHours], slot_interval_minutes: int
    ) -> None:
        position: int
        weekday_hours: WeekdayHours
        for position, weekday_hours in enumerate(weekly_hours):
            if isinstance(weekday_hours, OpenWeekday):
                cls._verify_time_on_slot_grid(
                    restaurant_seed_file, f"$.weekly_hours[{position}].opens_at", weekday_hours.opens_at, slot_interval_minutes
                )

    # Seed bookings stand for bookings guests made by phone, so they keep to the policy a phone booking is held to.
    @staticmethod
    def _verify_reservation_party_sizes(
        reservations_seed_file: SeedFile, seed_reservations: Sequence[SeedReservation], reservation_policy: ReservationPolicy
    ) -> None:
        position: int
        seed_reservation: SeedReservation
        for position, seed_reservation in enumerate(seed_reservations):
            if not reservation_policy.minimum_party_size <= seed_reservation.party_size <= reservation_policy.maximum_party_size:
                raise reservations_seed_file.fail(
                    f"$.reservations[{position}].party_size",
                    (
                        f"must be between {reservation_policy.minimum_party_size} and {reservation_policy.maximum_party_size}, "
                        f"the party sizes the reservation policy allows, but was {seed_reservation.party_size}"
                    ),
                )

    @classmethod
    def _verify_reservation_tables(
        cls, reservations_seed_file: SeedFile, seed_reservations: Sequence[SeedReservation], dining_tables: Sequence[DiningTable]
    ) -> None:
        seats_by_table_id: dict[str, int] = {dining_table.table_id: dining_table.seats for dining_table in dining_tables}
        position: int
        seed_reservation: SeedReservation
        for position, seed_reservation in enumerate(seed_reservations):
            table_path: str = f"$.reservations[{position}].{cls.TABLE_ID_KEY}"
            if seed_reservation.table_id not in seats_by_table_id:
                raise reservations_seed_file.fail(table_path, f"names table '{seed_reservation.table_id}', which tables.json does not list")
            if seats_by_table_id[seed_reservation.table_id] < seed_reservation.party_size:
                raise reservations_seed_file.fail(
                    table_path, f"names table '{seed_reservation.table_id}', which is too small for a party of {seed_reservation.party_size}"
                )

    @classmethod
    def _verify_reservation_seating_times(cls, reservations_seed_file: SeedFile, restaurant_seed: RestaurantSeed) -> None:
        seating_duration_minutes: int = restaurant_seed.restaurant_profile.reservation_policy.seating_duration_minutes
        slot_interval_minutes: int = restaurant_seed.restaurant_profile.reservation_policy.slot_interval_minutes
        weekday_hours_by_weekday: dict[Weekday, WeekdayHours] = {
            weekday_hours.weekday: weekday_hours for weekday_hours in restaurant_seed.weekly_hours
        }
        position: int
        seed_reservation: SeedReservation
        for position, seed_reservation in enumerate(restaurant_seed.seed_reservations):
            starts_at_path: str = f"$.reservations[{position}].starts_at"
            weekday_hours: WeekdayHours = weekday_hours_by_weekday[seed_reservation.weekday]
            if not isinstance(weekday_hours, OpenWeekday):
                raise reservations_seed_file.fail(starts_at_path, f"falls on a {seed_reservation.weekday.value}, when the restaurant does not open")
            cls._verify_time_on_slot_grid(reservations_seed_file, starts_at_path, seed_reservation.starts_at, slot_interval_minutes)
            cls._verify_seating_fits_weekday_hours(
                reservations_seed_file, starts_at_path, seed_reservation.starts_at, weekday_hours, seating_duration_minutes
            )
            overlapping_seed_reservation: SeedReservation | None = cls._find_overlapping_seed_reservation(
                restaurant_seed.seed_reservations[:position], seed_reservation, seating_duration_minutes
            )
            if overlapping_seed_reservation is not None:
                raise reservations_seed_file.fail(
                    starts_at_path,
                    (
                        f"seats table '{seed_reservation.table_id}' while booking '{overlapping_seed_reservation.confirmation_code}' "
                        f"still holds it on {seed_reservation.weekday.value}"
                    ),
                )

    @classmethod
    def _verify_time_on_slot_grid(cls, seed_file: SeedFile, value_path: str, time_of_day: time, slot_interval_minutes: int) -> None:
        if cls._to_minutes(time_of_day) % slot_interval_minutes != 0:
            raise seed_file.fail(
                value_path, f"'{time_of_day:%H:%M}' must fall on the {slot_interval_minutes}-minute slot grid that bookable times follow"
            )

    @classmethod
    def _verify_seating_fits_weekday_hours(
        cls,
        reservations_seed_file: SeedFile,
        starts_at_path: str,
        starts_at: time,
        open_weekday: OpenWeekday,
        seating_duration_minutes: int,
    ) -> None:
        starts_at_minutes: int = cls._to_minutes(starts_at)
        if starts_at_minutes < cls._to_minutes(open_weekday.opens_at) or (
            starts_at_minutes + seating_duration_minutes > cls._to_minutes(open_weekday.closes_at)
        ):
            raise reservations_seed_file.fail(
                starts_at_path,
                (
                    f"'{starts_at:%H:%M}' leaves no full {seating_duration_minutes}-minute seating between "
                    f"{open_weekday.opens_at:%H:%M} and {open_weekday.closes_at:%H:%M} on {open_weekday.weekday.value}"
                ),
            )

    @classmethod
    def _find_overlapping_seed_reservation(
        cls, earlier_seed_reservations: Sequence[SeedReservation], seed_reservation: SeedReservation, seating_duration_minutes: int
    ) -> SeedReservation | None:
        starts_at_minutes: int = cls._to_minutes(seed_reservation.starts_at)
        return next(
            (
                earlier_seed_reservation
                for earlier_seed_reservation in earlier_seed_reservations
                if earlier_seed_reservation.weekday == seed_reservation.weekday
                and earlier_seed_reservation.table_id == seed_reservation.table_id
                and cls._to_minutes(earlier_seed_reservation.starts_at) < starts_at_minutes + seating_duration_minutes
                and starts_at_minutes < cls._to_minutes(earlier_seed_reservation.starts_at) + seating_duration_minutes
            ),
            None,
        )

    @classmethod
    def _to_minutes(cls, time_of_day: time) -> int:
        return time_of_day.hour * cls.MINUTES_PER_HOUR + time_of_day.minute
