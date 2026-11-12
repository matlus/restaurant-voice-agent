from collections.abc import Mapping


class HostSettingsSource:
    """The one place the web host's settings are read from: the environment the process started with."""

    def __init__(self, environment_variables: Mapping[str, str]) -> None:
        self._environment_variables: Mapping[str, str] = environment_variables

    def read_setting_text(self, variable_name: str) -> str | None:
        """The setting's text, trimmed, or None when it is unset or blank."""
        setting_text: str = self._environment_variables.get(variable_name, "").strip()
        return setting_text or None
