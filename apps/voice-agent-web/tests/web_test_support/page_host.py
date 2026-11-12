import threading
import time
from types import TracebackType
from typing import Final, Self

import uvicorn
from fastapi import FastAPI

PAGE_HOST_ADDRESS: Final[str] = "127.0.0.1"
PAGE_HOST_START_TIMEOUT_SECONDS: Final[float] = 10.0
PAGE_HOST_STOP_TIMEOUT_SECONDS: Final[float] = 10.0
PAGE_HOST_START_POLL_SECONDS: Final[float] = 0.01


class PageHost:
    """The web app served over real HTTP and WebSocket on a free port of this machine, so a real browser can load the
    page and hold calls. It runs on its own thread, as the production server would run in its own process."""

    def __init__(self, app: FastAPI) -> None:
        self._server: uvicorn.Server = uvicorn.Server(uvicorn.Config(app, host=PAGE_HOST_ADDRESS, port=0, log_level="warning", lifespan="on"))
        self._server_thread: threading.Thread = threading.Thread(target=self._server.run, name="page-host", daemon=True)
        self._port: int | None = None

    @property
    def base_url(self) -> str:
        if self._port is None:
            raise RuntimeError("The page host has not started.")
        return f"http://{PAGE_HOST_ADDRESS}:{self._port}/"

    def __enter__(self) -> Self:
        self._server_thread.start()
        deadline: float = time.monotonic() + PAGE_HOST_START_TIMEOUT_SECONDS
        while not self._server.started:
            if not self._server_thread.is_alive() or time.monotonic() > deadline:
                # __exit__ does not run when __enter__ fails, so a server that starts late is stopped here.
                self._stop_server()
                raise RuntimeError("The page host did not start listening.")
            time.sleep(PAGE_HOST_START_POLL_SECONDS)
        # Port 0 lets the system choose a free port, and uvicorn offers no public way to read it back, so it is read
        # from the listening socket's (host, port) address.
        self._port = self._server.servers[0].sockets[0].getsockname()[1]
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None) -> None:
        self._stop_server()

    def _stop_server(self) -> None:
        self._server.should_exit = True
        self._server_thread.join(PAGE_HOST_STOP_TIMEOUT_SECONDS)
        if self._server_thread.is_alive():
            raise RuntimeError("The page host did not stop in time.")
