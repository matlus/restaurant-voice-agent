from collections.abc import Collection
from typing import Final

from voice_agent_web.exceptions.host_setting_exception import HostSettingException
from voice_agent_web.origins.origin_normalization import OriginNormalization


class ValidatorHostSettings:
    """Checks the settings the host is assembled with, before anything is built from them."""

    ALLOWED_ORIGINS_SETTING_NAME: Final[str] = "allowed_origins"
    MAXIMUM_CONCURRENT_CALLS_SETTING_NAME: Final[str] = "maximum_concurrent_calls"
    PORT_SETTING_NAME: Final[str] = "port"
    HIGHEST_PORT: Final[int] = 65_535

    @classmethod
    def validate_allowed_origins(cls, allowed_origins: Collection[str]) -> frozenset[str]:
        """The allowed origins, normalized. An origin with no scheme names no site, so trusting it would trust nothing."""
        normalized_allowed_origins: set[str] = set()
        allowed_origin: str
        for allowed_origin in allowed_origins:
            normalized_allowed_origin: str | None = OriginNormalization.normalize_origin(allowed_origin)
            if normalized_allowed_origin is None:
                raise HostSettingException(
                    f"Allowed origin '{allowed_origin}' must name a scheme and a host, such as https://booking.example.com.",
                    cls.ALLOWED_ORIGINS_SETTING_NAME,
                    allowed_origin,
                )
            normalized_allowed_origins.add(normalized_allowed_origin)
        return frozenset(normalized_allowed_origins)

    @classmethod
    def validate_maximum_concurrent_calls(cls, maximum_concurrent_calls: int) -> int:
        # With no call slot every caller would be told all lines are busy.
        if maximum_concurrent_calls < 1:
            raise HostSettingException(
                f"The maximum number of concurrent calls must be at least 1 but was {maximum_concurrent_calls}.",
                cls.MAXIMUM_CONCURRENT_CALLS_SETTING_NAME,
                str(maximum_concurrent_calls),
            )
        return maximum_concurrent_calls

    @classmethod
    def validate_port(cls, port: int) -> int:
        if not 1 <= port <= cls.HIGHEST_PORT:
            raise HostSettingException(f"The port must be between 1 and {cls.HIGHEST_PORT} but was {port}.", cls.PORT_SETTING_NAME, str(port))
        return port
