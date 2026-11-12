# Class tests for MiddlewareWebSocketOrigin, driven directly with a scripted ASGI app. They prove a handshake from a page
# on another site, from a sandboxed page or without a host to compare against is refused before the app sees it, that
# this host's own page, an allowed site and a client that names no origin reach the app untouched, and that plain HTTP
# is never subjected to the origin check.

from collections.abc import Sequence
from typing import Final

import pytest
from starlette.types import Message, Receive, Scope, Send

from voice_agent_web.middleware.middleware_websocket_origin import MiddlewareWebSocketOrigin

OWN_HOST: Final[str] = "voice.example.com"
ALLOWED_ORIGIN: Final[str] = "https://booking.example.com"
POLICY_VIOLATION_CLOSE_CODE: Final[int] = 1008
WEBSOCKET_CONNECT_MESSAGE: Final[Message] = {"type": "websocket.connect"}


class ScriptedAsgiApp:
    """The app behind the middleware: it records each scope it is handed and does nothing else."""

    def __init__(self) -> None:
        self.received_scope_types: list[str] = []

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        self.received_scope_types.append(scope["type"])


class ScriptedAsgiServer:
    """The server's side of one connection: hands over the client's connect message and records what is sent back."""

    def __init__(self) -> None:
        self.sent_messages: list[Message] = []

    async def receive(self) -> Message:
        return WEBSOCKET_CONNECT_MESSAGE

    async def send(self, message: Message) -> None:
        self.sent_messages.append(message)


def create_scope(scope_type: str, header_pairs: Sequence[tuple[str, str]]) -> Scope:
    # ASGI carries header names and values as bytes in latin-1.
    encoded_header_pairs: list[tuple[bytes, bytes]] = []
    header_name: str
    header_value: str
    for header_name, header_value in header_pairs:
        encoded_header_pairs.append((header_name.encode("latin-1"), header_value.encode("latin-1")))
    return {"type": scope_type, "path": "/conversation", "query_string": b"", "headers": encoded_header_pairs}


class TestMiddlewareWebSocketOrigin:
    @pytest.mark.parametrize(
        "header_pairs",
        [
            pytest.param([("host", OWN_HOST), ("origin", "https://attacker.example.net")], id="a-page-on-another-site"),
            pytest.param([("host", OWN_HOST), ("origin", "null")], id="a-sandboxed-page-naming-no-site"),
            pytest.param([("origin", f"https://{OWN_HOST}")], id="no-host-to-compare-the-origin-against"),
        ],
    )
    async def test_Call_WhenTheOriginIsNotOneThisHostTrusts_ThenTheHandshakeIsRefusedAndTheAppNeverSeesIt(
        self, header_pairs: list[tuple[str, str]]
    ) -> None:
        scripted_asgi_app: ScriptedAsgiApp = ScriptedAsgiApp()
        scripted_asgi_server: ScriptedAsgiServer = ScriptedAsgiServer()
        middleware_websocket_origin: MiddlewareWebSocketOrigin = MiddlewareWebSocketOrigin(
            scripted_asgi_app, allowed_origins=frozenset({ALLOWED_ORIGIN})
        )
        scope: Scope = create_scope("websocket", header_pairs)
        expected_outcome: tuple[list[Message], list[str]] = ([{"type": "websocket.close", "code": POLICY_VIOLATION_CLOSE_CODE}], [])

        await middleware_websocket_origin(scope, scripted_asgi_server.receive, scripted_asgi_server.send)

        actual_outcome: tuple[list[Message], list[str]] = (scripted_asgi_server.sent_messages, scripted_asgi_app.received_scope_types)
        assert actual_outcome == expected_outcome

    @pytest.mark.parametrize(
        "header_pairs",
        [
            pytest.param([("host", OWN_HOST), ("origin", f"https://{OWN_HOST}")], id="this-hosts-own-page"),
            pytest.param([("host", OWN_HOST), ("origin", "HTTPS://Booking.Example.com/")], id="an-allowed-site-in-any-case"),
            pytest.param([("host", OWN_HOST)], id="a-client-naming-no-origin"),
        ],
    )
    async def test_Call_WhenTheOriginIsOneThisHostTrusts_ThenTheAppReceivesTheHandshakeAndNothingIsSentForIt(
        self, header_pairs: list[tuple[str, str]]
    ) -> None:
        scripted_asgi_app: ScriptedAsgiApp = ScriptedAsgiApp()
        scripted_asgi_server: ScriptedAsgiServer = ScriptedAsgiServer()
        middleware_websocket_origin: MiddlewareWebSocketOrigin = MiddlewareWebSocketOrigin(
            scripted_asgi_app, allowed_origins=frozenset({ALLOWED_ORIGIN})
        )
        scope: Scope = create_scope("websocket", header_pairs)
        expected_outcome: tuple[list[Message], list[str]] = ([], ["websocket"])

        await middleware_websocket_origin(scope, scripted_asgi_server.receive, scripted_asgi_server.send)

        actual_outcome: tuple[list[Message], list[str]] = (scripted_asgi_server.sent_messages, scripted_asgi_app.received_scope_types)
        assert actual_outcome == expected_outcome

    async def test_Call_WhenAPlainHttpRequestNamesAnUntrustedOrigin_ThenTheAppReceivesItBecauseOnlyWebSocketsAreChecked(self) -> None:
        scripted_asgi_app: ScriptedAsgiApp = ScriptedAsgiApp()
        scripted_asgi_server: ScriptedAsgiServer = ScriptedAsgiServer()
        middleware_websocket_origin: MiddlewareWebSocketOrigin = MiddlewareWebSocketOrigin(
            scripted_asgi_app, allowed_origins=frozenset({ALLOWED_ORIGIN})
        )
        scope: Scope = create_scope("http", [("host", OWN_HOST), ("origin", "https://attacker.example.net")])
        expected_outcome: tuple[list[Message], list[str]] = ([], ["http"])

        await middleware_websocket_origin(scope, scripted_asgi_server.receive, scripted_asgi_server.send)

        actual_outcome: tuple[list[Message], list[str]] = (scripted_asgi_server.sent_messages, scripted_asgi_app.received_scope_types)
        assert actual_outcome == expected_outcome
