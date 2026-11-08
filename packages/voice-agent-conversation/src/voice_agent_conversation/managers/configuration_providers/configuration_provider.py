from collections.abc import Mapping

from voice_agent_conversation.managers.configuration_providers.settings_models.openai_realtime_settings import OpenAIRealtimeSettings
from voice_agent_conversation.managers.configuration_providers.settings_providers.settings_provider_openai_realtime import (
    SettingsProviderOpenAIRealtime,
)


class ConfigurationProvider:
    """Typed access to configuration, which the manager reads to build the speech gateway.

    Tests arrange configuration through override_by_environment_variable_name, which takes precedence
    over environment variables per variable; production passes no overrides.
    """

    def __init__(self, override_by_environment_variable_name: Mapping[str, str] | None = None) -> None:
        self._settings_provider_openai_realtime: SettingsProviderOpenAIRealtime = SettingsProviderOpenAIRealtime(
            override_by_environment_variable_name
        )

    def get_openai_realtime_settings(self) -> OpenAIRealtimeSettings:
        return self._settings_provider_openai_realtime.get_openai_realtime_settings()
