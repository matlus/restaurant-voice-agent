# Class tests for the store the connector creates: how it journals and which rows it refuses on its own. The domain's
# validation stops bad bookings before they reach the store, so no facade scenario can show the store's own guards.

import sqlite3
from pathlib import Path
from typing import Final

import pytest

from acceptance_support.service_locator_testing import WEDNESDAY_AFTERNOON_UTC, ClockFixed
from voice_agent_restaurant.managers.data_managers.store.restaurant_store_connector import RestaurantStoreConnector
from voice_agent_restaurant.managers.models.store_models import StoreSeeding

# A booking at 19:00 that keeps every store rule except, in each test, the one value that test breaks.
INSERT_RESERVATION_STATEMENT: Final[str] = """
    INSERT INTO reservations (
        confirmation_code, guest_name, phone_number, party_size, reservation_date, starts_at_minutes, ends_at_minutes,
        table_id, notes, status, created_at_utc, updated_at_utc
    ) VALUES ('ACDEFG', 'Store Test', '5557000000', :party_size, '2026-11-05', 1140, :ends_at_minutes,
        'T01', NULL, :status, '2026-11-04T21:00:00+00:00', '2026-11-04T21:00:00+00:00')
"""


def create_restaurant_store_connector(restaurant_database_path: Path) -> RestaurantStoreConnector:
    return RestaurantStoreConnector(restaurant_database_path, StoreSeeding.RESTAURANT_ONLY, ClockFixed(WEDNESDAY_AFTERNOON_UTC))


class TestRestaurantStoreConnector:
    def test_OpenConnection_WhenTheStoreIsNew_ThenItIsCreatedWithWriteAheadLogging(self, restaurant_database_path: Path) -> None:
        expected_journal_mode: str = "wal"

        with create_restaurant_store_connector(restaurant_database_path).open_connection() as connection:
            actual_journal_mode_row: sqlite3.Row = connection.execute("PRAGMA journal_mode").fetchone()

        assert actual_journal_mode_row[0] == expected_journal_mode

    def test_Insert_WhenAReservationHasNoGuests_ThenTheStoreRefusesIt(self, restaurant_database_path: Path) -> None:
        expected_error_phrase: str = "CHECK constraint failed: party_size > 0"

        with (
            create_restaurant_store_connector(restaurant_database_path).open_connection() as connection,
            pytest.raises(sqlite3.IntegrityError) as raised,
        ):
            connection.execute(INSERT_RESERVATION_STATEMENT, {"party_size": 0, "ends_at_minutes": 1260, "status": "booked"})

        assert expected_error_phrase in str(raised.value)

    def test_Insert_WhenAReservationEndsAsItStarts_ThenTheStoreRefusesIt(self, restaurant_database_path: Path) -> None:
        expected_error_phrase: str = "CHECK constraint failed: ends_at_minutes > starts_at_minutes"

        with (
            create_restaurant_store_connector(restaurant_database_path).open_connection() as connection,
            pytest.raises(sqlite3.IntegrityError) as raised,
        ):
            connection.execute(INSERT_RESERVATION_STATEMENT, {"party_size": 2, "ends_at_minutes": 1140, "status": "booked"})

        assert expected_error_phrase in str(raised.value)

    def test_Insert_WhenAReservationHasAnUnknownStatus_ThenTheStoreRefusesIt(self, restaurant_database_path: Path) -> None:
        expected_error_phrase: str = "CHECK constraint failed: status IN"

        with (
            create_restaurant_store_connector(restaurant_database_path).open_connection() as connection,
            pytest.raises(sqlite3.IntegrityError) as raised,
        ):
            connection.execute(INSERT_RESERVATION_STATEMENT, {"party_size": 2, "ends_at_minutes": 1260, "status": "pending"})

        assert expected_error_phrase in str(raised.value)
