from typing import final


@final
class HostSettingException(Exception):
    """A setting the web host was started with cannot be used. Raised while the app is assembled, so the process stops
    at startup instead of serving requests that would all fail."""

    def __init__(self, message: str, setting_name: str, setting_value: str) -> None:
        super().__init__(message)
        self.setting_name: str = setting_name
        self.setting_value: str = setting_value
