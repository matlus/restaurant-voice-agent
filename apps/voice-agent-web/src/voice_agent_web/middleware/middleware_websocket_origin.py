import logging
from collections.abc import Collection
from typing import Final
from urllib.parse import SplitResult, urlsplit

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Receive, Scope, Send


class MiddlewareWebSocketOrigin:
    """Refuses a WebSocket handshake that a page on another site started.

    Browsers do not apply the same-origin policy to WebSockets, and they send the site's cookies with the handshake, so
    without this check any page a signed-in user visits could open a call on their behalf. A browser always names the
    page's origin; the handshake is accepted when that origin is this host itself or one of the allowed origins. A
    client that names no origin is not a browser, and cookies are not its concern, so it passes.
    """

    POLICY_VIOLATION_CLOSE_CODE: Final[int] = 1008
    ORIGIN_HEADER_NAME: Final[str] = "origin"
    HOST_HEADER_NAME: Final[str] = "host"

    def __init__(self, app: ASGIApp, allowed_origins: Collection[str]) -> None:
        self._app: ASGIApp = app
        self._allowed_origins: frozenset[str] = self._normalize_allowed_origins(allowed_origins)
        self._logger: logging.Logger = logging.getLogger(__name__)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "websocket" or self._allows_origin(Headers(scope=scope)):
            await self._app(scope, receive, send)
            return
        self._logger.warning("Refused a WebSocket handshake for %s from origin %s", scope["path"], Headers(scope=scope).get(self.ORIGIN_HEADER_NAME))
        # The handshake starts with the client's connect message; closing before accepting refuses it.
        await receive()
        await send({"type": "websocket.close", "code": self.POLICY_VIOLATION_CLOSE_CODE})

    def _allows_origin(self, headers: Headers) -> bool:
        origin: str | None = headers.get(self.ORIGIN_HEADER_NAME)
        if origin is None:
            return True
        # An origin with no scheme or host, such as the "null" a sandboxed page sends, names no site to trust.
        normalized_origin: str | None = self._normalize_origin(origin)
        if normalized_origin is None:
            return False
        own_host: str | None = headers.get(self.HOST_HEADER_NAME)
        return normalized_origin in self._allowed_origins or (own_host is not None and urlsplit(normalized_origin).netloc == own_host.lower())

    @classmethod
    def _normalize_allowed_origins(cls, allowed_origins: Collection[str]) -> frozenset[str]:
        normalized_allowed_origins: set[str] = set()
        allowed_origin: str
        for allowed_origin in allowed_origins:
            normalized_allowed_origin: str | None = cls._normalize_origin(allowed_origin)
            # A bare host names no scheme; accepting it would leave an allowed origin that names no site.
            if normalized_allowed_origin is None:
                raise ValueError(f"Allowed origin '{allowed_origin}' must name a scheme and a host, such as https://booking.example.com.")
            normalized_allowed_origins.add(normalized_allowed_origin)
        return frozenset(normalized_allowed_origins)

    @staticmethod
    def _normalize_origin(origin: str) -> str | None:
        """An origin is scheme, host and port; case and a trailing slash do not change it. None when it names no site."""
        split_origin: SplitResult = urlsplit(origin.strip().lower())
        if split_origin.scheme == "" or split_origin.netloc == "":
            return None
        return f"{split_origin.scheme}://{split_origin.netloc}"
