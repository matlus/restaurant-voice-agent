import math
from collections.abc import Mapping
from typing import Final

from voice_agent_conversation.managers.configuration_providers.settings_models.call_limit_settings import CallLimitSettings
from voice_agent_conversation.managers.configuration_providers.settings_source import SettingsSource
from voice_agent_conversation.managers.exceptions.configuration_exceptions import ConfigurationSettingException, LogEventConfiguration


class SettingsProviderCallLimits:
    """Reads and validates the call limits eagerly, so a malformed limit surfaces at startup. Each limit has a production
    default, so only a deliberate change needs a setting."""

    MAXIMUM_CALL_SECONDS_VARIABLE_NAME: Final[str] = "VOICE_AGENT_MAXIMUM_CALL_SECONDS"
    MAXIMUM_SILENCE_SECONDS_VARIABLE_NAME: Final[str] = "VOICE_AGENT_MAXIMUM_SILENCE_SECONDS"
    # A reservation call rarely lasts five minutes; fifteen leaves room for a slow one.
    DEFAULT_MAXIMUM_CALL_SECONDS: Final[float] = 900.0
    # Long enough for a caller to look something up, short enough that a forgotten tab stops costing money.
    DEFAULT_MAXIMUM_SILENCE_SECONDS: Final[float] = 120.0
    SECONDS_FORM_DESCRIPTION: Final[str] = "a finite number of seconds"
    ENVIRONMENT_VARIABLE_NAME_CONTEXT_KEY: Final[str] = "Configuration.EnvironmentVariableName"
    SETTING_VALUE_CONTEXT_KEY: Final[str] = "Configuration.SettingValue"

    def __init__(self, override_by_environment_variable_name: Mapping[str, str] | None = None) -> None:
        self._settings_source: SettingsSource = SettingsSource(override_by_environment_variable_name)
        self._call_limit_settings: CallLimitSettings = self._initialize_settings()

    def get_call_limit_settings(self) -> CallLimitSettings:
        return self._call_limit_settings

    def _initialize_settings(self) -> CallLimitSettings:
        return CallLimitSettings(
            maximum_call_seconds=self._read_positive_seconds(self.MAXIMUM_CALL_SECONDS_VARIABLE_NAME, self.DEFAULT_MAXIMUM_CALL_SECONDS),
            maximum_silence_seconds=self._read_positive_seconds(self.MAXIMUM_SILENCE_SECONDS_VARIABLE_NAME, self.DEFAULT_MAXIMUM_SILENCE_SECONDS),
        )

    def _read_positive_seconds(self, variable_name: str, default_seconds: float) -> float:
        raw_value: str | None = self._settings_source.read_setting_value(variable_name)
        if not SettingsSource.is_setting_present(raw_value):
            return default_seconds
        try:
            seconds: float = float(raw_value.strip())
        except ValueError as value_error:
            raise self._create_not_positive_exception(variable_name, raw_value) from value_error
        # float() also reads "nan" and "inf", which would disable the limit or keep it from ever being reached.
        if not math.isfinite(seconds) or seconds <= 0:
            raise self._create_not_positive_exception(variable_name, raw_value)
        return seconds

    def _create_not_positive_exception(self, variable_name: str, raw_value: str) -> ConfigurationSettingException:
        return ConfigurationSettingException(
            message=(
                f"Configuration setting '{variable_name}' must be {self.SECONDS_FORM_DESCRIPTION} greater than zero but was '{raw_value.strip()}'. "
                "Leave it unset to use the default."
            ),
            log_event=LogEventConfiguration.CALL_LIMIT_SETTINGS_RETRIEVAL,
            contextual_data_by_name={self.ENVIRONMENT_VARIABLE_NAME_CONTEXT_KEY: variable_name, self.SETTING_VALUE_CONTEXT_KEY: raw_value.strip()},
        )
