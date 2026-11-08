from pathlib import Path

from starlette.staticfiles import StaticFiles
from starlette.types import Receive, Scope, Send
from starlette.websockets import WebSocketClose


class StaticAssetsApp:
    """Serves the microphone page's files over HTTP. StaticFiles answers HTTP alone, so a WebSocket handshake to any
    path the router does not route is refused here, as the router refuses one it cannot match."""

    def __init__(self, static_folder: Path) -> None:
        self._static_files: StaticFiles = StaticFiles(directory=static_folder, html=True)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "websocket":
            await WebSocketClose()(scope, receive, send)
            return
        await self._static_files(scope, receive, send)
