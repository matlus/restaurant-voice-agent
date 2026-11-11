from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, override

from voice_agent_restaurant import ClockBase, ConfigurationProvider, DomainFacade, ServiceLocatorBase

DATABASE_PATH_VARIABLE_NAME: Final[str] = "VOICE_AGENT_RESTAURANT_DATABASE_PATH"
SEED_DEMO_BOOKINGS_VARIABLE_NAME: Final[str] = "VOICE_AGENT_RESTAURANT_SEED_DEMO_BOOKINGS"

# Wednesday 2026-11-04 at 15:00 in Riverton (America/Chicago, UTC-6 after daylight saving ends).
# The seed places its bookings on the next Wednesday (today), Friday, Saturday, Sunday and Tuesday: 2026-11-04, 06, 07,
# 08 and 10.
WEDNESDAY_AFTERNOON_UTC: Final[datetime] = datetime(2026, 11, 4, 21, 0, tzinfo=UTC)
# Thursday 2026-11-05 at 18:45 in Riverton, a quiet evening with every table free a quarter of an hour ahead.
THURSDAY_EARLY_EVENING_UTC: Final[datetime] = datetime(2026, 11, 6, 0, 45, tzinfo=UTC)
# Friday 2026-11-06 at 19:10 in Riverton, ten minutes into the busiest seating.
FRIDAY_EVENING_UTC: Final[datetime] = datetime(2026, 11, 7, 1, 10, tzinfo=UTC)


class ClockFixed(ClockBase):
    def __init__(self, fixed_now_utc: datetime) -> None:
        self._fixed_now_utc: datetime = fixed_now_utc

    @override
    def now_utc(self) -> datetime:
        return self._fixed_now_utc


class ServiceLocatorTesting(ServiceLocatorBase):
    # The clock is the one component swapped, so "now" is the same on every run.

    def __init__(self, override_by_environment_variable_name: Mapping[str, str], fixed_now_utc: datetime) -> None:
        self._override_by_environment_variable_name: Mapping[str, str] = override_by_environment_variable_name
        self._fixed_now_utc: datetime = fixed_now_utc

    @override
    def get_configuration_provider(self) -> ConfigurationProvider:
        return ConfigurationProvider(self._override_by_environment_variable_name)

    @override
    def create_clock(self) -> ClockBase:
        return ClockFixed(self._fixed_now_utc)


def create_domain_facade(database_path: Path, fixed_now_utc: datetime = WEDNESDAY_AFTERNOON_UTC) -> DomainFacade:
    # The single place tests create the DomainFacade. Each test passes its own temporary database file, which the
    # facade creates and seeds with the demo bookings, so every test starts from the same restaurant and bookings.
    return DomainFacade(
        ServiceLocatorTesting({DATABASE_PATH_VARIABLE_NAME: str(database_path), SEED_DEMO_BOOKINGS_VARIABLE_NAME: "true"}, fixed_now_utc)
    )


def create_domain_facade_without_demo_bookings(database_path: Path, fixed_now_utc: datetime = WEDNESDAY_AFTERNOON_UTC) -> DomainFacade:
    # As a real deployment starts: the restaurant, its hours, tables and menu, and no bookings.
    return DomainFacade(ServiceLocatorTesting({DATABASE_PATH_VARIABLE_NAME: str(database_path)}, fixed_now_utc))
