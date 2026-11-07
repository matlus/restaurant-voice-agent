from collections.abc import Mapping

from voice_agent_restaurant.managers.configuration_providers.settings_models.restaurant_store_settings import RestaurantStoreSettings
from voice_agent_restaurant.managers.configuration_providers.settings_providers.settings_provider_restaurant_store import (
    SettingsProviderRestaurantStore,
)


class ConfigurationProvider:
    """Typed access to configuration. Accessed only by managers, obtained from the service locator.

    Real in every test run. Tests arrange configuration through override_by_environment_variable_name,
    which takes precedence over environment variables per variable; production passes no overrides.
    """

    def __init__(self, override_by_environment_variable_name: Mapping[str, str] | None = None) -> None:
        self._settings_provider_restaurant_store: SettingsProviderRestaurantStore = SettingsProviderRestaurantStore(
            override_by_environment_variable_name
        )

    def get_restaurant_store_settings(self) -> RestaurantStoreSettings:
        return self._settings_provider_restaurant_store.get_restaurant_store_settings()
