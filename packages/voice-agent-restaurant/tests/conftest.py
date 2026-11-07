from pathlib import Path

import pytest


@pytest.fixture
def restaurant_database_path(tmp_path: Path) -> Path:
    return tmp_path / "restaurant.sqlite3"
