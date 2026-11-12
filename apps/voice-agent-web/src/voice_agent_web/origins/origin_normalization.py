import ipaddress
from typing import Final
from urllib.parse import SplitResult, urlsplit


class OriginNormalization:
    """An origin is scheme, host and port; case, a trailing slash and the scheme's default port do not change it."""

    DEFAULT_PORT_BY_SCHEME: Final[dict[str, int]] = {"http": 80, "https": 443}

    @classmethod
    def normalize_origin(cls, origin: str) -> str | None:
        """The origin in one canonical spelling, as a browser sends it, or None when it names no site, as the "null" a
        sandboxed page sends. An origin carrying a user name names no site a browser would send either."""
        origin_parts: tuple[str, str, int | None] | None = cls._split_origin(origin)
        if origin_parts is None:
            return None
        return cls._compose_origin(*origin_parts)

    @staticmethod
    def read_host(normalized_origin: str) -> str:
        return urlsplit(normalized_origin).netloc

    @classmethod
    def _split_origin(cls, origin: str) -> tuple[str, str, int | None] | None:
        """The scheme, host and port, or None when the origin names no site."""
        # A malformed address, such as an unclosed IPv6 bracket, a port that is not a number or a host that cannot be
        # spelled in ASCII, names no site either.
        try:
            split_origin: SplitResult = urlsplit(origin.strip().lower())
            origin_port: int | None = split_origin.port
            if not split_origin.scheme or not split_origin.hostname or "@" in split_origin.netloc:
                return None
            return split_origin.scheme, cls._to_origin_host(split_origin.hostname), origin_port
        except ValueError:
            return None

    @staticmethod
    def _to_origin_host(hostname: str) -> str:
        """The host as a browser spells it: an IPv6 address compressed and in brackets, which hostname drops, and any
        other name in ASCII, with international names in their punycode form."""
        if ":" in hostname:
            return f"[{ipaddress.IPv6Address(hostname).compressed}]"
        return hostname.encode("idna").decode("ascii")

    @classmethod
    def _compose_origin(cls, scheme: str, origin_host: str, origin_port: int | None) -> str:
        if origin_port is None or origin_port == cls.DEFAULT_PORT_BY_SCHEME.get(scheme):
            return f"{scheme}://{origin_host}"
        return f"{scheme}://{origin_host}:{origin_port}"
