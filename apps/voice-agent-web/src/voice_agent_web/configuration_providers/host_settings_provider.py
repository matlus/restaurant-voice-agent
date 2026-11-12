from collections.abc import Mapping
from typing import Final

from voice_agent_web.configuration_providers.host_settings import HostSettings
from voice_agent_web.exceptions.host_setting_exception import HostSettingException


class HostSettingsProvider:
    """Reads the web host's own settings from the environment when it is built, so a setting that is not a number stops
    startup with a message naming it instead of a bare ValueError."""

    HOST_VARIABLE_NAME: Final[str] = "VOICE_AGENT_WEB_HOST"
    PORT_VARIABLE_NAME: Final[str] = "VOICE_AGENT_WEB_PORT"
    # Comma-separated origins, such as https://booking.example.com, of other sites whose pages may open a call.
    ALLOWED_ORIGINS_VARIABLE_NAME: Final[str] = "VOICE_AGENT_WEB_ALLOWED_ORIGINS"
    MAXIMUM_CONCURRENT_CALLS_VARIABLE_NAME: Final[str] = "VOICE_AGENT_MAXIMUM_CONCURRENT_CALLS"
    DEFAULT_HOST: Final[str] = "127.0.0.1"
    DEFAULT_PORT: Final[int] = 8000
    DEFAULT_MAXIMUM_CONCURRENT_CALLS: Final[int] = 10
    ORIGIN_SEPARATOR: Final[str] = ","

    def __init__(self, environment_variables: Mapping[str, str]) -> None:
        self._environment_variables: Mapping[str, str] = environment_variables
        self._host_settings: HostSettings = HostSettings(
            host=self._read_text(self.HOST_VARIABLE_NAME) or self.DEFAULT_HOST,
            port=self._read_whole_number(self.PORT_VARIABLE_NAME, self.DEFAULT_PORT),
            allowed_origins=self._read_allowed_origins(),
            maximum_concurrent_calls=self._read_whole_number(self.MAXIMUM_CONCURRENT_CALLS_VARIABLE_NAME, self.DEFAULT_MAXIMUM_CONCURRENT_CALLS),
        )

    def get_host_settings(self) -> HostSettings:
        return self._host_settings

    def _read_text(self, variable_name: str) -> str:
        return self._environment_variables.get(variable_name, "").strip()

    def _read_whole_number(self, variable_name: str, default_value: int) -> int:
        setting_text: str = self._read_text(variable_name)
        if not setting_text:
            return default_value
        # isdecimal, unlike int(), refuses a sign, spaces inside and digits from other scripts.
        if not setting_text.isascii() or not setting_text.isdecimal():
            raise HostSettingException(
                f"Setting '{variable_name}' must be a whole number but was '{setting_text}'. Leave it unset to use {default_value}.",
                variable_name,
                setting_text,
            )
        return int(setting_text)

    def _read_allowed_origins(self) -> list[str]:
        return [
            allowed_origin.strip()
            for allowed_origin in self._read_text(self.ALLOWED_ORIGINS_VARIABLE_NAME).split(self.ORIGIN_SEPARATOR)
            if allowed_origin.strip()
        ]
