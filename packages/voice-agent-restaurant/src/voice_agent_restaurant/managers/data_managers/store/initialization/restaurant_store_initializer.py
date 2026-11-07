import json
import sqlite3
from collections.abc import Sequence
from datetime import date, datetime, time, timedelta
from typing import Final
from zoneinfo import ZoneInfo

from voice_agent_restaurant.managers.data_managers.store.initialization.restaurant_store_schema import SCHEMA_STATEMENTS, STORE_VERSION
from voice_agent_restaurant.managers.data_managers.store.initialization.seed_data.seed_data_reader import (
    RestaurantSeed,
    SeedDataReader,
    SeedReservation,
)
from voice_agent_restaurant.managers.models.menu_models import DishRecord
from voice_agent_restaurant.managers.models.reservation_models import ReservationStatus
from voice_agent_restaurant.managers.models.restaurant_models import (
    Closure,
    DiningTable,
    OpenWeekday,
    RestaurantProfile,
    Weekday,
    WeekdayHours,
)

type _StoredValue = str | int | None


class RestaurantStoreInitializer:
    """Creates the schema and loads the bundled seed into a new store, exactly once per database file.

    Every connection reads the store's version, which costs one PRAGMA. Only a store below STORE_VERSION is
    initialized, inside one IMMEDIATE transaction that reads the version again, so two first callers racing
    on a new file cannot both seed it.
    """

    MINUTES_PER_HOUR: Final[int] = 60
    DAYS_PER_WEEK: Final[int] = 7

    @classmethod
    def ensure_initialized(cls, connection: sqlite3.Connection, now_utc: datetime) -> None:
        if cls._is_current(connection):
            return
        connection.execute("BEGIN IMMEDIATE")
        try:
            if not cls._is_current(connection):
                cls._create_schema(connection)
                cls._load_seed(connection, SeedDataReader.read_restaurant_seed(), now_utc)
                connection.execute(f"PRAGMA user_version = {STORE_VERSION}")
            connection.execute("COMMIT")
        except BaseException:
            # SQLite rolls some failed transactions back by itself; a second ROLLBACK would raise and hide the first error.
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise

    @staticmethod
    def _is_current(connection: sqlite3.Connection) -> bool:
        version_row: sqlite3.Row | None = connection.execute("PRAGMA user_version").fetchone()
        return version_row is not None and int(version_row[0]) >= STORE_VERSION

    @staticmethod
    def _create_schema(connection: sqlite3.Connection) -> None:
        for schema_statement in SCHEMA_STATEMENTS:
            connection.execute(schema_statement)

    @classmethod
    def _load_seed(cls, connection: sqlite3.Connection, restaurant_seed: RestaurantSeed, now_utc: datetime) -> None:
        restaurant_profile: RestaurantProfile = restaurant_seed.restaurant_profile
        cls._insert_restaurant(connection, restaurant_profile)
        cls._insert_weekly_hours(connection, restaurant_seed.weekly_hours)
        cls._insert_closures(connection, restaurant_seed.closures)
        cls._insert_dining_tables(connection, restaurant_seed.dining_tables)
        cls._insert_dishes(connection, restaurant_seed.dish_records)
        restaurant_today: date = now_utc.astimezone(ZoneInfo(restaurant_profile.time_zone)).date()
        cls._insert_seed_reservations(
            connection, restaurant_seed.seed_reservations, restaurant_today, restaurant_profile.reservation_policy.seating_duration_minutes, now_utc
        )

    @staticmethod
    def _insert_restaurant(connection: sqlite3.Connection, restaurant_profile: RestaurantProfile) -> None:
        connection.execute(
            """
            INSERT INTO restaurant (
                restaurant_id, name, tagline, description, street_address, city, state_or_region, postal_code, phone_number,
                time_zone, house_notes_json, seating_duration_minutes, slot_interval_minutes, minimum_party_size,
                maximum_party_size, booking_window_days, minimum_lead_time_minutes, late_arrival_hold_minutes, large_party_guidance
            ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                restaurant_profile.name,
                restaurant_profile.tagline,
                restaurant_profile.description,
                restaurant_profile.street_address,
                restaurant_profile.city,
                restaurant_profile.state_or_region,
                restaurant_profile.postal_code,
                restaurant_profile.phone_number,
                restaurant_profile.time_zone,
                json.dumps(restaurant_profile.house_notes),
                restaurant_profile.reservation_policy.seating_duration_minutes,
                restaurant_profile.reservation_policy.slot_interval_minutes,
                restaurant_profile.reservation_policy.minimum_party_size,
                restaurant_profile.reservation_policy.maximum_party_size,
                restaurant_profile.reservation_policy.booking_window_days,
                restaurant_profile.reservation_policy.minimum_lead_time_minutes,
                restaurant_profile.reservation_policy.late_arrival_hold_minutes,
                restaurant_profile.reservation_policy.large_party_guidance,
            ),
        )

    @classmethod
    def _insert_weekly_hours(cls, connection: sqlite3.Connection, weekly_hours: Sequence[WeekdayHours]) -> None:
        weekly_hours_rows: list[tuple[_StoredValue, ...]] = []
        for weekday_hours in weekly_hours:
            weekday_index: int = list(Weekday).index(weekday_hours.weekday)
            if isinstance(weekday_hours, OpenWeekday):
                weekly_hours_rows.append(
                    (weekday_index, cls._to_minutes_after_midnight(weekday_hours.opens_at), cls._to_minutes_after_midnight(weekday_hours.closes_at))
                )
            else:
                weekly_hours_rows.append((weekday_index, None, None))
        connection.executemany("INSERT INTO weekly_hours (weekday_index, opens_at_minutes, closes_at_minutes) VALUES (?, ?, ?)", weekly_hours_rows)

    @staticmethod
    def _insert_closures(connection: sqlite3.Connection, closures: Sequence[Closure]) -> None:
        connection.executemany(
            "INSERT INTO closures (closed_on, reason) VALUES (?, ?)", [(closure.closed_on.isoformat(), closure.reason) for closure in closures]
        )

    @staticmethod
    def _insert_dining_tables(connection: sqlite3.Connection, dining_tables: Sequence[DiningTable]) -> None:
        connection.executemany(
            "INSERT INTO dining_tables (table_id, seats, area) VALUES (?, ?, ?)",
            [(dining_table.table_id, dining_table.seats, dining_table.area) for dining_table in dining_tables],
        )

    @staticmethod
    def _insert_dishes(connection: sqlite3.Connection, dish_records: Sequence[DishRecord]) -> None:
        dish_rows: list[tuple[_StoredValue, ...]] = []
        menu_position: int
        dish_record: DishRecord
        for menu_position, dish_record in enumerate(dish_records):
            dish_rows.append(
                (
                    dish_record.dish_id,
                    menu_position,
                    dish_record.name,
                    dish_record.category.value,
                    dish_record.description,
                    dish_record.price_cents,
                    int(dish_record.contains_gluten),
                    dish_record.nutrition.calories,
                    dish_record.nutrition.protein_grams,
                    dish_record.nutrition.carbohydrate_grams,
                    dish_record.nutrition.fat_grams,
                    dish_record.cross_contact_note,
                    json.dumps(dish_record.ingredients),
                    json.dumps([allergen.value for allergen in dish_record.allergens]),
                    json.dumps([diet_label.value for diet_label in dish_record.recipe_diet_labels]),
                )
            )
        connection.executemany(
            """
            INSERT INTO dishes (
                dish_id, menu_position, name, category, description, price_cents, contains_gluten, calories, protein_grams,
                carbohydrate_grams, fat_grams, cross_contact_note, ingredients_json, allergens_json, recipe_diet_labels_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            dish_rows,
        )

    @classmethod
    def _insert_seed_reservations(
        cls,
        connection: sqlite3.Connection,
        seed_reservations: Sequence[SeedReservation],
        restaurant_today: date,
        seating_duration_minutes: int,
        now_utc: datetime,
    ) -> None:
        reservation_rows: list[tuple[_StoredValue, ...]] = []
        for seed_reservation in seed_reservations:
            days_until_weekday: int = (list(Weekday).index(seed_reservation.weekday) - restaurant_today.weekday()) % cls.DAYS_PER_WEEK
            reservation_date: date = restaurant_today + timedelta(days=days_until_weekday)
            starts_at_minutes: int = cls._to_minutes_after_midnight(seed_reservation.starts_at)
            reservation_rows.append(
                (
                    seed_reservation.confirmation_code,
                    seed_reservation.guest_name,
                    seed_reservation.phone_number,
                    seed_reservation.party_size,
                    reservation_date.isoformat(),
                    starts_at_minutes,
                    starts_at_minutes + seating_duration_minutes,
                    seed_reservation.table_id,
                    seed_reservation.notes,
                    ReservationStatus.BOOKED.value,
                    now_utc.isoformat(),
                    now_utc.isoformat(),
                )
            )
        connection.executemany(
            """
            INSERT INTO reservations (
                confirmation_code, guest_name, phone_number, party_size, reservation_date, starts_at_minutes, ends_at_minutes,
                table_id, notes, status, created_at_utc, updated_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            reservation_rows,
        )

    @classmethod
    def _to_minutes_after_midnight(cls, time_of_day: time) -> int:
        return time_of_day.hour * cls.MINUTES_PER_HOUR + time_of_day.minute
