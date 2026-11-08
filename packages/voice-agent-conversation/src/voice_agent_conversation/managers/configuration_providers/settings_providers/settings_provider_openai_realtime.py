from collections.abc import Mapping
from typing import Final

from voice_agent_conversation.managers.configuration_providers.settings_models.openai_realtime_settings import OpenAIRealtimeSettings
from voice_agent_conversation.managers.configuration_providers.settings_source import SettingsSource
from voice_agent_conversation.managers.exceptions.configuration_exceptions import ConfigurationSettingException, LogEventConfiguration


class SettingsProviderOpenAIRealtime:
    """Reads and validates the OpenAI Realtime settings eagerly, so a missing key surfaces at startup."""

    API_KEY_VARIABLE_NAME: Final[str] = "OPENAI_API_KEY"
    MODEL_VARIABLE_NAME: Final[str] = "VOICE_AGENT_OPENAI_REALTIME_MODEL"
    WEBSOCKET_BASE_URL_VARIABLE_NAME: Final[str] = "VOICE_AGENT_OPENAI_REALTIME_WEBSOCKET_BASE_URL"
    DEFAULT_MODEL: Final[str] = "gpt-realtime-2.1"
    WEBSOCKET_URL_SCHEMES: Final[tuple[str, ...]] = ("ws://", "wss://")
    ENVIRONMENT_VARIABLE_NAME_CONTEXT_KEY: Final[str] = "Configuration.EnvironmentVariableName"

    def __init__(self, override_by_environment_variable_name: Mapping[str, str] | None = None) -> None:
        self._settings_source: SettingsSource = SettingsSource(override_by_environment_variable_name)
        self._openai_realtime_settings: OpenAIRealtimeSettings = self._initialize_settings()

    def get_openai_realtime_settings(self) -> OpenAIRealtimeSettings:
        return self._openai_realtime_settings

    def _initialize_settings(self) -> OpenAIRealtimeSettings:
        return OpenAIRealtimeSettings(api_key=self._read_api_key(), model=self._read_model(), websocket_base_url=self._read_websocket_base_url())

    def _read_api_key(self) -> str:
        api_key_raw_value: str | None = self._settings_source.read_setting_value(self.API_KEY_VARIABLE_NAME)
        if not SettingsSource.is_setting_present(api_key_raw_value):
            raise ConfigurationSettingException(
                message=(
                    f"Configuration setting '{self.API_KEY_VARIABLE_NAME}' must contain an OpenAI API key "
                    f"but was {'missing' if api_key_raw_value is None else 'empty or whitespace'}. Add it to the gitignored .env file."
                ),
                log_event=LogEventConfiguration.OPENAI_REALTIME_SETTINGS_RETRIEVAL,
                contextual_data_by_name={
                    self.ENVIRONMENT_VARIABLE_NAME_CONTEXT_KEY: self.API_KEY_VARIABLE_NAME,
                    "Configuration.SettingWasMissing": api_key_raw_value is None,
                },
            )
        return api_key_raw_value.strip()

    def _read_model(self) -> str:
        model_raw_value: str | None = self._settings_source.read_setting_value(self.MODEL_VARIABLE_NAME)
        return model_raw_value.strip() if SettingsSource.is_setting_present(model_raw_value) else self.DEFAULT_MODEL

    def _read_websocket_base_url(self) -> str | None:
        websocket_base_url_raw_value: str | None = self._settings_source.read_setting_value(self.WEBSOCKET_BASE_URL_VARIABLE_NAME)
        if not SettingsSource.is_setting_present(websocket_base_url_raw_value):
            return None
        websocket_base_url: str = websocket_base_url_raw_value.strip()
        if not websocket_base_url.lower().startswith(self.WEBSOCKET_URL_SCHEMES):
            raise ConfigurationSettingException(
                message=(
                    f"Configuration setting '{self.WEBSOCKET_BASE_URL_VARIABLE_NAME}' must be a WebSocket URL starting with "
                    f"{' or '.join(self.WEBSOCKET_URL_SCHEMES)} but was '{websocket_base_url}'. Leave it unset to use OpenAI's own address."
                ),
                log_event=LogEventConfiguration.OPENAI_REALTIME_SETTINGS_RETRIEVAL,
                contextual_data_by_name={
                    self.ENVIRONMENT_VARIABLE_NAME_CONTEXT_KEY: self.WEBSOCKET_BASE_URL_VARIABLE_NAME,
                    "Configuration.SettingValue": websocket_base_url,
                },
            )
        return websocket_base_url
