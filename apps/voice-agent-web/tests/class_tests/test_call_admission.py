# Class tests for create_call_admission, driven directly with a scripted ASGI app. They prove a call beyond the limit is
# accepted only to be told all lines are busy and closed with 1013 while the app never sees it, that a slot comes back
# once a call ends, and that plain HTTP is never counted against the limit.

import asyncio
import json
from typing import Final

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from voice_agent_web.middleware.call_admission import create_call_admission

ONE_CALL_AT_A_TIME: Final[int] = 1
# A call let through that should have been refused waits for a slot that never frees; this turns that hang into a failure.
TEST_TIME_LIMIT_SECONDS: Final[float] = 5.0
TRY_AGAIN_LATER_CLOSE_CODE: Final[int] = 1013
# The page shows this title, and the socket closes with it as the reason.
LINES_BUSY_TITLE: Final[str] = "All lines are busy"
WEBSOCKET_CONNECT_MESSAGE: Final[Message] = {"type": "websocket.connect"}
WEBSOCKET_SCOPE: Final[Scope] = {"type": "websocket", "path": "/conversation", "query_string": b"", "headers": []}
HTTP_SCOPE: Final[Scope] = {"type": "http", "path": "/voices", "query_string": b"", "headers": []}


class ScriptedAsgiApp:
    """The app behind the admission: it records each scope it is handed and, while asked to, holds every call open."""

    def __init__(self) -> None:
        self.received_scope_types: list[str] = []
        self.call_is_held: asyncio.Event = asyncio.Event()
        self.held_calls_may_end: asyncio.Event = asyncio.Event()
        self.held_calls_may_end.set()

    def hold_calls_open(self) -> None:
        self.held_calls_may_end.clear()

    def let_held_calls_end(self) -> None:
        self.held_calls_may_end.set()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        self.received_scope_types.append(scope["type"])
        if scope["type"] == "websocket":
            self.call_is_held.set()
            await self.held_calls_may_end.wait()


class ScriptedAsgiServer:
    """The server's side of one connection: hands over the client's connect message and records what is sent back."""

    def __init__(self) -> None:
        self.sent_messages: list[Message] = []

    async def receive(self) -> Message:
        return WEBSOCKET_CONNECT_MESSAGE

    async def send(self, message: Message) -> None:
        self.sent_messages.append(message)


class TestCallAdmission:
    async def test_Call_WhenEveryAllowedCallIsInProgress_ThenTheCallerIsToldAllLinesAreBusyAndTheAppNeverSeesTheCall(self) -> None:
        scripted_asgi_app: ScriptedAsgiApp = ScriptedAsgiApp()
        call_admission: ASGIApp = create_call_admission(scripted_asgi_app, maximum_concurrent_calls=ONE_CALL_AT_A_TIME)
        busy_caller_scripted_asgi_server: ScriptedAsgiServer = ScriptedAsgiServer()
        expected_outcome: tuple[list[Message], list[str]] = (
            [
                {"type": "websocket.accept"},
                {
                    "type": "websocket.send",
                    "text": json.dumps(
                        {
                            "type": "error",
                            "title": LINES_BUSY_TITLE,
                            "detail": "All lines are busy right now. Please try again in a few minutes.",
                        }
                    ),
                },
                {"type": "websocket.close", "code": TRY_AGAIN_LATER_CLOSE_CODE, "reason": LINES_BUSY_TITLE},
            ],
            ["websocket"],
        )
        scripted_asgi_app.hold_calls_open()
        async with asyncio.timeout(TEST_TIME_LIMIT_SECONDS), asyncio.TaskGroup() as task_group:
            task_group.create_task(call_admission(WEBSOCKET_SCOPE, ScriptedAsgiServer().receive, ScriptedAsgiServer().send))
            await scripted_asgi_app.call_is_held.wait()

            await call_admission(WEBSOCKET_SCOPE, busy_caller_scripted_asgi_server.receive, busy_caller_scripted_asgi_server.send)

            scripted_asgi_app.let_held_calls_end()

        actual_outcome: tuple[list[Message], list[str]] = (busy_caller_scripted_asgi_server.sent_messages, scripted_asgi_app.received_scope_types)
        assert actual_outcome == expected_outcome

    async def test_Call_WhenTheEarlierCallHasEnded_ThenTheNextCallReachesTheApp(self) -> None:
        scripted_asgi_app: ScriptedAsgiApp = ScriptedAsgiApp()
        call_admission: ASGIApp = create_call_admission(scripted_asgi_app, maximum_concurrent_calls=ONE_CALL_AT_A_TIME)
        next_caller_scripted_asgi_server: ScriptedAsgiServer = ScriptedAsgiServer()
        await call_admission(WEBSOCKET_SCOPE, ScriptedAsgiServer().receive, ScriptedAsgiServer().send)
        expected_outcome: tuple[list[Message], list[str]] = ([], ["websocket", "websocket"])

        await call_admission(WEBSOCKET_SCOPE, next_caller_scripted_asgi_server.receive, next_caller_scripted_asgi_server.send)

        actual_outcome: tuple[list[Message], list[str]] = (next_caller_scripted_asgi_server.sent_messages, scripted_asgi_app.received_scope_types)
        assert actual_outcome == expected_outcome

    async def test_Call_WhenEveryAllowedCallIsInProgressAndAPlainHttpRequestArrives_ThenTheRequestReachesTheApp(self) -> None:
        scripted_asgi_app: ScriptedAsgiApp = ScriptedAsgiApp()
        call_admission: ASGIApp = create_call_admission(scripted_asgi_app, maximum_concurrent_calls=ONE_CALL_AT_A_TIME)
        http_client_scripted_asgi_server: ScriptedAsgiServer = ScriptedAsgiServer()
        expected_outcome: tuple[list[Message], list[str]] = ([], ["websocket", "http"])
        scripted_asgi_app.hold_calls_open()
        async with asyncio.timeout(TEST_TIME_LIMIT_SECONDS), asyncio.TaskGroup() as task_group:
            task_group.create_task(call_admission(WEBSOCKET_SCOPE, ScriptedAsgiServer().receive, ScriptedAsgiServer().send))
            await scripted_asgi_app.call_is_held.wait()

            await call_admission(HTTP_SCOPE, http_client_scripted_asgi_server.receive, http_client_scripted_asgi_server.send)

            scripted_asgi_app.let_held_calls_end()

        actual_outcome: tuple[list[Message], list[str]] = (http_client_scripted_asgi_server.sent_messages, scripted_asgi_app.received_scope_types)
        assert actual_outcome == expected_outcome
