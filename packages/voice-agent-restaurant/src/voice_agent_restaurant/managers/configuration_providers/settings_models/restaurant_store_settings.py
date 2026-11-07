from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RestaurantStoreSettings:
    database_path: Path
