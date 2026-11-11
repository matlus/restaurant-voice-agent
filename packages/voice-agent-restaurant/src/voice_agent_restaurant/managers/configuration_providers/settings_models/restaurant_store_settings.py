from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RestaurantStoreSettings:
    """Where the store lives, and whether a new store is seeded with demo bookings as well as the restaurant itself."""

    database_path: Path
    seeds_demo_bookings: bool
