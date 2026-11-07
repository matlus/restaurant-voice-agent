import json
from importlib import resources
from typing import Any, Final

RESTAURANT_SEED_FILE_NAME: Final[str] = "restaurant.json"
TABLES_SEED_FILE_NAME: Final[str] = "tables.json"
MENU_SEED_FILE_NAME: Final[str] = "menu.json"


def read_bundled_seed_file(seed_file_name: str) -> dict[str, Any]:
    """The bundled seed file a new store is created from, so a test derives its expectations from the seeded data itself."""
    seed_file_text: str = resources.files("voice_agent_restaurant").joinpath("seed_data", seed_file_name).read_text(encoding="utf-8")
    return json.loads(seed_file_text)
