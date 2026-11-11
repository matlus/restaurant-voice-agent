import json
import sqlite3
from collections.abc import Collection, Generator, Mapping, Sequence
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
from typing import Final
from zoneinfo import ZoneInfo

from voice_agent_restaurant.managers.data_managers.store.initialization.restaurant_store_schema import SCHEMA_STATEMENTS, STORE_VERSION
from voice_agent_restaurant.managers.data_managers.store.initialization.seed_data.seed_data_reader import (
    RestaurantSeed,
    SeedDataReader,
    SeedReservation,
)
from voice_agent_restaurant.managers.exceptions.restaurant_store_exceptions import RestaurantStoreContractViolationException
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

    Creating a store has three steps: the schema, the restaurant's reference data (profile, hours, closures, tables
    and menu), and, only when asked for, the demo bookings. Every connection reads the store's version, which costs
    one PRAGMA. Only a store below STORE_VERSION is initialized, inside one IMMEDIATE transaction that reads the
    version again, so two first callers racing on a new file cannot both seed it.
    """

    # SQLite reports this version for a file no store has been created in yet.
    NEW_FILE_STORE_VERSION: Final[int] = 0
    MINUTES_PER_HOUR: Final[int] = 60
    DAYS_PER_WEEK: Final[int] = 7

    @classmethod
    def ensure_initialized(cls, connection: sqlite3.Connection, now_utc: datetime, seeds_demo_bookings: bool) -> None:  # noqa: FBT001 - a setting's value, not a mode switch
        if cls._is_current(connection):
            return
        # Write-ahead logging lets readers carry on while one writer books. The mode belongs to the file and cannot
        # change inside a transaction, so it is set before the store is created; setting it twice is harmless.
        connection.execute("PRAGMA journal_mode = WAL")
        with cls._immediate_transaction(connection):
            cls._create_store(connection, now_utc, seeds_demo_bookings)

    @staticmethod
    @contextmanager
    def _immediate_transaction(connection: sqlite3.Connection) -> Generator[None]:
        connection.execute("BEGIN IMMEDIATE")
        try:
            yield
            connection.execute("COMMIT")
        except BaseException:
            # SQLite rolls some failed transactions back by itself; a second ROLLBACK would raise and hide the first error.
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise

    @classmethod
    def _create_store(cls, connection: sqlite3.Connection, now_utc: datetime, seeds_demo_bookings: bool) -> None:  # noqa: FBT001 - a setting's value, not a mode switch
        store_version: int = cls._read_store_version(connection)
        # A racing first caller may have created the store between the unlocked check and this transaction.
        if cls._is_store_version_current(store_version):
            return
        if store_version != cls.NEW_FILE_STORE_VERSION:
            raise RestaurantStoreContractViolationException(
                message=(
                    f"The restaurant store was created by an older version of the app (store version {store_version}; this version needs "
                    f"{STORE_VERSION}), and it cannot be upgraded in place. Delete the store file; it is created and seeded again on the next run."
                ),
                contextual_data_by_name={"RestaurantStore.Version": store_version, "RestaurantStore.RequiredVersion": STORE_VERSION},
            )
        restaurant_seed: RestaurantSeed = SeedDataReader.read_restaurant_seed()
        cls._create_schema(connection)
        cls._insert_reference_data(connection, restaurant_seed)
        if seeds_demo_bookings:
            cls._insert_demo_bookings(connection, restaurant_seed, now_utc)
        # SQLite PRAGMA statements take no bound parameters, so the version is interpolated; STORE_VERSION is an int constant, never input.
        connection.execute(f"PRAGMA user_version = {STORE_VERSION}")

    @classmethod
    def _is_current(cls, connection: sqlite3.Connection) -> bool:
        return cls._is_store_version_current(cls._read_store_version(connection))

    @staticmethod
    def _is_store_version_current(store_version: int) -> bool:
        return store_version >= STORE_VERSION

    @classmethod
    def _read_store_version(cls, connection: sqlite3.Connection) -> int:
        version_row: sqlite3.Row | None = connection.execute("PRAGMA user_version").fetchone()
        return cls.NEW_FILE_STORE_VERSION if version_row is None else int(version_row[0])

    @staticmethod
    def _create_schema(connection: sqlite3.Connection) -> None:
        for schema_statement in SCHEMA_STATEMENTS:
            connection.execute(schema_statement)

    @classmethod
    def _insert_reference_data(cls, connection: sqlite3.Connection, restaurant_seed: RestaurantSeed) -> None:
        cls._insert_restaurant(connection, restaurant_seed.restaurant_profile)
        cls._insert_weekly_hours(connection, restaurant_seed.weekly_hours)
        cls._insert_closures(connection, restaurant_seed.closures)
        cls._insert_dining_tables(connection, restaurant_seed.dining_tables)
        cls._insert_dishes(connection, restaurant_seed.dish_records)

    @classmethod
    def _insert_demo_bookings(cls, connection: sqlite3.Connection, restaurant_seed: RestaurantSeed, now_utc: datetime) -> None:
        restaurant_profile: RestaurantProfile = restaurant_seed.restaurant_profile
        restaurant_today: date = now_utc.astimezone(ZoneInfo(restaurant_profile.time_zone)).date()
        cls._insert_seed_reservations(
            connection,
            restaurant_seed.seed_reservations,
            cls._find_first_open_weekday_dates(restaurant_today, {closure.closed_on for closure in restaurant_seed.closures}),
            restaurant_profile.reservation_policy.seating_duration_minutes,
            now_utc,
        )

    @staticmethod
    def _insert_restaurant(connection: sqlite3.Connection, restaurant_profile: RestaurantProfile) -> None:
        connection.execute(
            """
            INSERT INTO restaurant (
                restaurant_id, name, tagline, description, street_address, city, state_or_region, postal_code, phone_number,
                time_zone, allergen_notice, house_notes_json, seating_duration_minutes, slot_interval_minutes, minimum_party_size,
                maximum_party_size, booking_window_days, late_arrival_hold_minutes, large_party_guidance
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
                restaurant_profile.allergen_notice,
                json.dumps(restaurant_profile.house_notes),
                restaurant_profile.reservation_policy.seating_duration_minutes,
                restaurant_profile.reservation_policy.slot_interval_minutes,
                restaurant_profile.reservation_policy.minimum_party_size,
                restaurant_profile.reservation_policy.maximum_party_size,
                restaurant_profile.reservation_policy.booking_window_days,
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
    def _find_first_open_weekday_dates(cls, restaurant_today: date, closed_dates: Collection[date]) -> dict[Weekday, date]:
        """The date each seed booking's weekday next falls on, from today on, skipping holiday closures a week at a time,
        so no seed booking lands on a day the restaurant is closed."""
        reservation_date_by_weekday: dict[Weekday, date] = {}
        days_ahead: int
        for days_ahead in range(cls.DAYS_PER_WEEK):
            reservation_date: date = restaurant_today + timedelta(days=days_ahead)
            while reservation_date in closed_dates:
                reservation_date += timedelta(days=cls.DAYS_PER_WEEK)
            reservation_date_by_weekday[list(Weekday)[reservation_date.weekday()]] = reservation_date
        return reservation_date_by_weekday

    @classmethod
    def _insert_seed_reservations(
        cls,
        connection: sqlite3.Connection,
        seed_reservations: Sequence[SeedReservation],
        reservation_date_by_weekday: Mapping[Weekday, date],
        seating_duration_minutes: int,
        now_utc: datetime,
    ) -> None:
        reservation_rows: list[tuple[_StoredValue, ...]] = []
        for seed_reservation in seed_reservations:
            reservation_date: date = reservation_date_by_weekday[seed_reservation.weekday]
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
