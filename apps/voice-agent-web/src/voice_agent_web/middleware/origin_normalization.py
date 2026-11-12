from typing import Final
from urllib.parse import SplitResult, urlsplit


class OriginNormalization:
    """An origin is scheme, host and port; case, a trailing slash and the scheme's default port do not change it."""

    DEFAULT_PORT_BY_SCHEME: Final[dict[str, int]] = {"http": 80, "https": 443}

    @classmethod
    def normalize_origin(cls, origin: str) -> str | None:
        """The origin in one canonical spelling, as a browser sends it, or None when it names no site, as the "null" a
        sandboxed page sends. An origin carrying a user name names no site a browser would send either."""
        split_origin: SplitResult = urlsplit(origin.strip().lower())
        if not split_origin.scheme or not split_origin.hostname or "@" in split_origin.netloc:
            return None
        try:
            origin_port: int | None = split_origin.port
        except ValueError:
            return None
        # hostname drops the brackets around an IPv6 address, which the origin keeps.
        origin_host: str = f"[{split_origin.hostname}]" if ":" in split_origin.hostname else split_origin.hostname
        if origin_port is None or origin_port == cls.DEFAULT_PORT_BY_SCHEME.get(split_origin.scheme):
            return f"{split_origin.scheme}://{origin_host}"
        return f"{split_origin.scheme}://{origin_host}:{origin_port}"

    @staticmethod
    def read_host(normalized_origin: str) -> str:
        return urlsplit(normalized_origin).netloc
