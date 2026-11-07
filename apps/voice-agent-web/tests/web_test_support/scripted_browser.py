from collections.abc import Sequence

from starlette.types import Message, Scope
from starlette.websockets import WebSocket


class ScriptedBrowser:
    """The browser's end of one WebSocket, played by the test without hosting anything.

    It hands the app the scripted messages in order, starting with the connect, and records every message the app
    sends. A lost connection refuses every frame after the handshake the way the server does, with an OSError, and
    records what it refused.
    """

    def __init__(self, *, query_string: bytes, browser_messages: Sequence[Message] = (), connection_is_lost: bool = False) -> None:
        self._query_string: bytes = query_string
        self._pending_messages: list[Message] = [{"type": "websocket.connect"}, *browser_messages]
        self._connection_is_lost: bool = connection_is_lost
        self.delivered_messages: list[Message] = []
        self.refused_messages: list[Message] = []

    def create_websocket(self) -> WebSocket:
        websocket_scope: Scope = {
            "type": "websocket",
            "path": "/conversation",
            "query_string": self._query_string,
            "headers": [],
            "scheme": "ws",
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
        }
        return WebSocket(websocket_scope, self._receive, self._send)

    async def _receive(self) -> Message:
        assert self._pending_messages, "The handler read past everything the scripted browser sends."
        return self._pending_messages.pop(0)

    async def _send(self, message: Message) -> None:
        if self._connection_is_lost and message["type"] != "websocket.accept":
            self.refused_messages.append(message)
            raise OSError("The connection to the browser is lost.")
        self.delivered_messages.append(message)
