import sqlite3
from collections.abc import Generator
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Final

from voice_agent_restaurant.managers.clocks.clock_base import ClockBase
from voice_agent_restaurant.managers.data_managers.store.initialization.restaurant_store_initializer import RestaurantStoreInitializer


class RestaurantStoreConnector:
    """Opens connections to the restaurant SQLite file. A connection to a new file creates and seeds the store first,
    with the demo bookings only when the settings ask for them.

    Connections are opened per operation and closed right after, in whichever worker thread runs the
    operation. Transactions are explicit (isolation_level=None), so each data manager decides where
    a transaction begins and ends. The connector keeps no state between connections.
    """

    BUSY_TIMEOUT_SECONDS: Final[float] = 5.0

    def __init__(self, database_path: Path, seeds_demo_bookings: bool, clock: ClockBase) -> None:  # noqa: FBT001 - a setting's value, not a mode switch
        self._database_path: Path = database_path
        self._seeds_demo_bookings: bool = seeds_demo_bookings
        self._clock: ClockBase = clock

    @contextmanager
    def open_connection(self) -> Generator[sqlite3.Connection]:
        with closing(self._connect()) as connection:
            RestaurantStoreInitializer.ensure_initialized(connection, self._clock.now_utc(), self._seeds_demo_bookings)
            yield connection

    def _connect(self) -> sqlite3.Connection:
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        connection: sqlite3.Connection = sqlite3.connect(self._database_path, timeout=self.BUSY_TIMEOUT_SECONDS, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection
