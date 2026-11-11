# Class tests for the store the connector creates: how it journals and which rows it refuses on its own. The domain's
# validation stops bad bookings before they reach the store, so no facade scenario can show the store's own guards.

import sqlite3
from pathlib import Path
from typing import Final

import pytest

from acceptance_support.service_locator_testing import WEDNESDAY_AFTERNOON_UTC, ClockFixed
from voice_agent_restaurant.managers.data_managers.store.restaurant_store_connector import RestaurantStoreConnector

INSERT_RESERVATION_STATEMENT: Final[str] = """
    INSERT INTO reservations (
        confirmation_code, guest_name, phone_number, party_size, reservation_date, starts_at_minutes, ends_at_minutes,
        table_id, notes, status, created_at_utc, updated_at_utc
    ) VALUES ('ACDEFG', 'Store Test', '5557000000', :party_size, '2026-11-05', :starts_at_minutes, :ends_at_minutes,
        'T01', NULL, :status, '2026-11-04T21:00:00+00:00', '2026-11-04T21:00:00+00:00')
"""


def create_restaurant_store_connector(restaurant_database_path: Path) -> RestaurantStoreConnector:
    return RestaurantStoreConnector(restaurant_database_path, False, ClockFixed(WEDNESDAY_AFTERNOON_UTC))


class TestRestaurantStoreConnector:
    def test_OpenConnection_WhenTheStoreIsNew_ThenItIsCreatedWithWriteAheadLogging(self, restaurant_database_path: Path) -> None:
        expected_journal_mode: str = "wal"

        with create_restaurant_store_connector(restaurant_database_path).open_connection() as connection:
            journal_mode_row: sqlite3.Row = connection.execute("PRAGMA journal_mode").fetchone()

        assert journal_mode_row[0] == expected_journal_mode

    @pytest.mark.parametrize(
        ("party_size", "starts_at_minutes", "ends_at_minutes", "status"),
        [
            (0, 1140, 1260, "booked"),
            (2, 1140, 1140, "booked"),
            (2, 1140, 1260, "pending"),
        ],
        ids=["no guests", "ends as it starts", "unknown status"],
    )
    def test_Insert_WhenAReservationRowBreaksTheStoreRules_ThenTheStoreRefusesIt(
        self, restaurant_database_path: Path, party_size: int, starts_at_minutes: int, ends_at_minutes: int, status: str
    ) -> None:
        expected_error_phrase: str = "CHECK constraint failed"

        with (
            create_restaurant_store_connector(restaurant_database_path).open_connection() as connection,
            pytest.raises(sqlite3.IntegrityError) as raised,
        ):
            connection.execute(
                INSERT_RESERVATION_STATEMENT,
                {"party_size": party_size, "starts_at_minutes": starts_at_minutes, "ends_at_minutes": ends_at_minutes, "status": status},
            )

        assert expected_error_phrase in str(raised.value)
