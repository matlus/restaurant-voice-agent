import os
from collections.abc import Mapping
from typing import TypeGuard


class SettingsSource:
    """The one seam through which settings providers read configuration values.

    Reads the process environment, with per-variable overrides taking precedence so tests
    can arrange configuration without mutating the process environment.
    """

    def __init__(self, override_by_environment_variable_name: Mapping[str, str] | None = None) -> None:
        self._override_by_environment_variable_name: dict[str, str] = (
            dict(override_by_environment_variable_name) if override_by_environment_variable_name else {}
        )

    def read_setting_value(self, variable_name: str) -> str | None:
        if variable_name in self._override_by_environment_variable_name:
            return self._override_by_environment_variable_name[variable_name]
        return os.environ.get(variable_name)

    @staticmethod
    def is_setting_present(setting_raw_value: str | None) -> TypeGuard[str]:
        # Absent, empty, and whitespace-only all mean the setting was not provided.
        return setting_raw_value is not None and setting_raw_value.strip() != ""
