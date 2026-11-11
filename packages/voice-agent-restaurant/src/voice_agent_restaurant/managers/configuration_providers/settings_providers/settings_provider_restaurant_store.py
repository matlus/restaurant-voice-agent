from collections.abc import Mapping
from pathlib import Path
from typing import Final

from voice_agent_restaurant.managers.configuration_providers.settings_models.restaurant_store_settings import RestaurantStoreSettings
from voice_agent_restaurant.managers.configuration_providers.settings_providers.settings_source import SettingsSource
from voice_agent_restaurant.managers.exceptions.configuration_exceptions import ConfigurationSettingException, LogEventConfiguration


class SettingsProviderRestaurantStore:
    """Reads and validates the restaurant store settings eagerly, so a bad setting surfaces at startup."""

    DATABASE_PATH_VARIABLE_NAME: Final[str] = "VOICE_AGENT_RESTAURANT_DATABASE_PATH"
    SEED_DEMO_BOOKINGS_VARIABLE_NAME: Final[str] = "VOICE_AGENT_RESTAURANT_SEED_DEMO_BOOKINGS"
    # Off unless asked for: a real deployment must not start with strangers' bookings holding its tables.
    SEEDS_DEMO_BOOKINGS_BY_DEFAULT: Final[bool] = False
    BOOLEAN_BY_SETTING_TEXT: Final[dict[str, bool]] = {"true": True, "false": False}
    ENVIRONMENT_VARIABLE_NAME_CONTEXT_KEY: Final[str] = "Configuration.EnvironmentVariableName"
    NUL_CHARACTER: Final[str] = chr(0)

    def __init__(self, override_by_environment_variable_name: Mapping[str, str] | None = None) -> None:
        self._settings_source: SettingsSource = SettingsSource(override_by_environment_variable_name)
        self._restaurant_store_settings: RestaurantStoreSettings = self._initialize_settings()

    def get_restaurant_store_settings(self) -> RestaurantStoreSettings:
        return self._restaurant_store_settings

    def _initialize_settings(self) -> RestaurantStoreSettings:
        return RestaurantStoreSettings(database_path=self._read_database_path(), seeds_demo_bookings=self._read_seeds_demo_bookings())

    def _read_database_path(self) -> Path:
        database_path_raw_value: str | None = self._settings_source.read_setting_value(self.DATABASE_PATH_VARIABLE_NAME)
        if not SettingsSource.is_setting_present(database_path_raw_value):
            raise ConfigurationSettingException(
                message=(
                    f"Configuration setting '{self.DATABASE_PATH_VARIABLE_NAME}' must contain the path of the restaurant SQLite database file "
                    f"but was {'missing' if database_path_raw_value is None else 'empty or whitespace'}. "
                    "The file is created and seeded on first use if it does not exist."
                ),
                log_event=LogEventConfiguration.RESTAURANT_STORE_SETTINGS_RETRIEVAL,
                contextual_data_by_name={
                    self.ENVIRONMENT_VARIABLE_NAME_CONTEXT_KEY: self.DATABASE_PATH_VARIABLE_NAME,
                    "Configuration.SettingWasMissing": database_path_raw_value is None,
                },
            )
        database_path_text: str = database_path_raw_value.strip()
        if self.NUL_CHARACTER in database_path_text:
            # Path() accepts a NUL character, but every file-system call then fails with a bare ValueError.
            raise ConfigurationSettingException(
                message=f"Configuration setting '{self.DATABASE_PATH_VARIABLE_NAME}' is not a usable file path because it contains a NUL character.",
                log_event=LogEventConfiguration.RESTAURANT_STORE_SETTINGS_RETRIEVAL,
                contextual_data_by_name={self.ENVIRONMENT_VARIABLE_NAME_CONTEXT_KEY: self.DATABASE_PATH_VARIABLE_NAME},
            )
        return Path(database_path_text)

    def _read_seeds_demo_bookings(self) -> bool:
        seed_demo_bookings_raw_value: str | None = self._settings_source.read_setting_value(self.SEED_DEMO_BOOKINGS_VARIABLE_NAME)
        if not SettingsSource.is_setting_present(seed_demo_bookings_raw_value):
            return self.SEEDS_DEMO_BOOKINGS_BY_DEFAULT
        seeds_demo_bookings: bool | None = self.BOOLEAN_BY_SETTING_TEXT.get(seed_demo_bookings_raw_value.strip().casefold())
        if seeds_demo_bookings is None:
            raise ConfigurationSettingException(
                message=(
                    f"Configuration setting '{self.SEED_DEMO_BOOKINGS_VARIABLE_NAME}' must be 'true' or 'false' "
                    f"but was '{seed_demo_bookings_raw_value.strip()}'."
                ),
                log_event=LogEventConfiguration.RESTAURANT_STORE_SETTINGS_RETRIEVAL,
                contextual_data_by_name={self.ENVIRONMENT_VARIABLE_NAME_CONTEXT_KEY: self.SEED_DEMO_BOOKINGS_VARIABLE_NAME},
            )
        return seeds_demo_bookings
