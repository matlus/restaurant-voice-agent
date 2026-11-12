from dataclasses import dataclass


@dataclass(frozen=True)
class HostSettings:
    """What the web host is started with: where it listens, which other sites' pages may open a call, and how many
    calls run at once."""

    host: str
    port: int
    allowed_origins: list[str]
    maximum_concurrent_calls: int
