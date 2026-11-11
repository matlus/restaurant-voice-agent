from dataclasses import dataclass
from pathlib import Path

from voice_agent_restaurant.managers.models.store_models import StoreSeeding


@dataclass(frozen=True)
class RestaurantStoreSettings:
    """Where the store lives, and what a new store is seeded with."""

    database_path: Path
    store_seeding: StoreSeeding
