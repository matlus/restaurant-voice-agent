# Class tests for MiddlewareExceptionTranslation: the boundary shell itself, driven directly with scripted ASGI apps so
# every branch is reachable without a real failure escaping a hosted pipeline. They prove which answer the shell sends
# for how far the connection had gone, that it never sends to a client that is gone, and that each failure is logged
# once. What the answer says is TestExceptionToWireTranslator's contract.

import json
import logging
from collections.abc import Sequence
from typing import Final

import pytest
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from starlette.websockets import WebSocketDisconnect

from voice_agent_conversation import RealtimeVoiceProviderUnavailableException, VoiceNotOfferedException
from voice_agent_conversation.managers.exceptions.conversation_exceptions import LogEventConversation
from voice_agent_conversation.managers.exceptions.realtime_voice_exceptions import LogEventRealtimeVoice
from voice_agent_web.middleware.middleware_exception_translation import MiddlewareExceptionTranslation
from voice_agent_web.middleware.translators.exception_to_wire_translator import ExceptionToWireTranslator

MIDDLEWARE_LOGGER_NAME: Final[str] = "voice_agent_web.middleware.middleware_exception_translation"
CONVERSATION_PATH: Final[str] = "/conversation"
VOICES_PATH: Final[str] = "/voices"
INTERNAL_FAILURE_DETAIL: Final[str] = "the cache index at /srv/cache is corrupt"


class ScriptedAsgiServer:
    """The server's side of one ASGI connection: hands the app the scripted messages and records what the app sends.

    A server whose client is gone refuses every frame after the handshake with an OSError, as a real server does
    before the app has read the disconnect, and records nothing it refused.
    """

    def __init__(self, client_messages: Sequence[Message], *, client_is_gone: bool = False) -> None:
        self._pending_messages: list[Message] = list(client_messages)
        self._client_is_gone: bool = client_is_gone
        self.sent_messages: list[Message] = []

    async def receive(self) -> Message:
        assert self._pending_messages, "The app read past everything the scripted client sends."
        return self._pending_messages.pop(0)

    async def send(self, message: Message) -> None:
        if self._client_is_gone and message["type"] != "websocket.accept":
            raise OSError("The client is gone.")
        self.sent_messages.append(message)


def create_app_that_fails(escaped_exception: Exception, app_messages: Sequence[Message] = (), *, app_reads_one_message: bool = False) -> ASGIApp:
    async def fail_after_scripted_steps(scope: Scope, receive: Receive, send: Send) -> None:
        app_message: Message
        for app_message in app_messages:
            await send(app_message)
        if app_reads_one_message:
            await receive()
        raise escaped_exception

    return fail_after_scripted_steps


def create_websocket_scope() -> Scope:
    return {"type": "websocket", "path": CONVERSATION_PATH, "query_string": b"", "headers": []}


def create_http_scope() -> Scope:
    return {"type": "http", "method": "GET", "path": VOICES_PATH, "query_string": b"", "headers": []}


def count_failure_logs(caplog: pytest.LogCaptureFixture) -> int:
    return len([log_record for log_record in caplog.records if log_record.name == MIDDLEWARE_LOGGER_NAME and log_record.levelno == logging.ERROR])


def create_voice_not_offered_exception() -> VoiceNotOfferedException:
    return VoiceNotOfferedException("openai-nova", ["openai-marin"], LogEventConversation.CONVERSATION_START)


class TestMiddlewareExceptionTranslationWebSocket:
    async def test_Call_WhenAWebSocketFailsAfterTheBrowserHungUp_ThenNothingMoreIsSentAndTheFailureIsLoggedOnce(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        realtime_voice_provider_unavailable_exception: RealtimeVoiceProviderUnavailableException = RealtimeVoiceProviderUnavailableException(
            "The provider dropped the session while winding down.", LogEventRealtimeVoice.EVENT_RECEIPT
        )
        scripted_asgi_server: ScriptedAsgiServer = ScriptedAsgiServer([{"type": "websocket.disconnect", "code": 1001}])
        middleware_exception_translation: MiddlewareExceptionTranslation = MiddlewareExceptionTranslation(
            create_app_that_fails(realtime_voice_provider_unavailable_exception, [{"type": "websocket.accept"}], app_reads_one_message=True)
        )
        expected_sent_messages: list[Message] = [{"type": "websocket.accept"}]
        expected_failure_log_count: int = 1

        with caplog.at_level(logging.ERROR, logger=MIDDLEWARE_LOGGER_NAME):
            await middleware_exception_translation(create_websocket_scope(), scripted_asgi_server.receive, scripted_asgi_server.send)

        assert (scripted_asgi_server.sent_messages, count_failure_logs(caplog)) == (expected_sent_messages, expected_failure_log_count)

    async def test_Call_WhenTheServerRefusesAFrameBecauseTheClientIsGone_ThenNothingMoreIsSentAndTheFailureIsLoggedOnce(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        # The frame's own failure escapes the app, which never got to read the disconnect.
        scripted_asgi_server: ScriptedAsgiServer = ScriptedAsgiServer([], client_is_gone=True)
        middleware_exception_translation: MiddlewareExceptionTranslation = MiddlewareExceptionTranslation(
            create_app_that_fails(create_voice_not_offered_exception(), [{"type": "websocket.accept"}, {"type": "websocket.send", "text": "{}"}])
        )
        expected_sent_messages: list[Message] = [{"type": "websocket.accept"}]
        expected_failure_log_count: int = 1

        with caplog.at_level(logging.ERROR, logger=MIDDLEWARE_LOGGER_NAME):
            await middleware_exception_translation(create_websocket_scope(), scripted_asgi_server.receive, scripted_asgi_server.send)

        assert (scripted_asgi_server.sent_messages, count_failure_logs(caplog)) == (expected_sent_messages, expected_failure_log_count)

    async def test_Call_WhenAnAcceptedWebSocketFails_ThenTheErrorFrameAndThenTheCloseAreSentAndTheFailureIsLoggedOnce(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        voice_not_offered_exception: VoiceNotOfferedException = create_voice_not_offered_exception()
        scripted_asgi_server: ScriptedAsgiServer = ScriptedAsgiServer([])
        middleware_exception_translation: MiddlewareExceptionTranslation = MiddlewareExceptionTranslation(
            create_app_that_fails(voice_not_offered_exception, [{"type": "websocket.accept"}])
        )
        expected_error_message_text: str = json.dumps(
            {"type": "error", "title": voice_not_offered_exception.reason, "detail": voice_not_offered_exception.message}
        )
        expected_sent_messages: list[Message] = [
            {"type": "websocket.accept"},
            {"type": "websocket.send", "text": expected_error_message_text},
            {"type": "websocket.close", "code": ExceptionToWireTranslator.POLICY_VIOLATION_CLOSE_CODE, "reason": voice_not_offered_exception.reason},
        ]
        expected_failure_log_count: int = 1

        with caplog.at_level(logging.ERROR, logger=MIDDLEWARE_LOGGER_NAME):
            await middleware_exception_translation(create_websocket_scope(), scripted_asgi_server.receive, scripted_asgi_server.send)

        assert (scripted_asgi_server.sent_messages, count_failure_logs(caplog)) == (expected_sent_messages, expected_failure_log_count)

    async def test_Call_WhenAWebSocketFailsBeforeTheHandshakeIsAccepted_ThenOnlyTheCloseIsSentToRefuseTheHandshake(self) -> None:
        voice_not_offered_exception: VoiceNotOfferedException = create_voice_not_offered_exception()
        scripted_asgi_server: ScriptedAsgiServer = ScriptedAsgiServer([])
        middleware_exception_translation: MiddlewareExceptionTranslation = MiddlewareExceptionTranslation(
            create_app_that_fails(voice_not_offered_exception)
        )
        expected_sent_messages: list[Message] = [
            {"type": "websocket.close", "code": ExceptionToWireTranslator.POLICY_VIOLATION_CLOSE_CODE, "reason": voice_not_offered_exception.reason},
        ]

        await middleware_exception_translation(create_websocket_scope(), scripted_asgi_server.receive, scripted_asgi_server.send)

        assert scripted_asgi_server.sent_messages == expected_sent_messages

    async def test_Call_WhenAFrameworkDisconnectEscapes_ThenItIsLoggedAsAnUnexpectedFailureNotTreatedAsAHangUp(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        scripted_asgi_server: ScriptedAsgiServer = ScriptedAsgiServer([])
        middleware_exception_translation: MiddlewareExceptionTranslation = MiddlewareExceptionTranslation(
            create_app_that_fails(WebSocketDisconnect(code=1006), [{"type": "websocket.accept"}])
        )
        expected_last_sent_message: Message = {
            "type": "websocket.close",
            "code": ExceptionToWireTranslator.INTERNAL_ERROR_CLOSE_CODE,
            "reason": ExceptionToWireTranslator.UNEXPECTED_FAILURE_TITLE,
        }
        expected_unexpected_failure_log_count: int = 1

        with caplog.at_level(logging.ERROR, logger=MIDDLEWARE_LOGGER_NAME):
            await middleware_exception_translation(create_websocket_scope(), scripted_asgi_server.receive, scripted_asgi_server.send)

        actual_unexpected_failure_log_count: int = len([log_record for log_record in caplog.records if "unexpectedly" in log_record.getMessage()])
        assert (scripted_asgi_server.sent_messages[-1], actual_unexpected_failure_log_count) == (
            expected_last_sent_message,
            expected_unexpected_failure_log_count,
        )


class TestMiddlewareExceptionTranslationHttp:
    async def test_Call_WhenAnHttpRequestFails_ThenProblemDetailsAreSentAndTheLoggedExceptionNamesTheRequest(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        voice_not_offered_exception: VoiceNotOfferedException = create_voice_not_offered_exception()
        scripted_asgi_server: ScriptedAsgiServer = ScriptedAsgiServer([{"type": "http.request", "body": b"", "more_body": False}])
        middleware_exception_translation: MiddlewareExceptionTranslation = MiddlewareExceptionTranslation(
            create_app_that_fails(voice_not_offered_exception)
        )
        expected_status_code: int = voice_not_offered_exception.http_status_code
        expected_request_context: str = f"http {VOICES_PATH}"
        expected_failure_log_count: int = 1

        with caplog.at_level(logging.ERROR, logger=MIDDLEWARE_LOGGER_NAME):
            await middleware_exception_translation(create_http_scope(), scripted_asgi_server.receive, scripted_asgi_server.send)

        actual_status_code: int = scripted_asgi_server.sent_messages[0]["status"]
        assert (actual_status_code, voice_not_offered_exception.contextual_data_by_name.get("Request"), count_failure_logs(caplog)) == (
            expected_status_code,
            expected_request_context,
            expected_failure_log_count,
        )

    async def test_Call_WhenAnUnexpectedExceptionEscapesAnHttpRequest_ThenNeitherItsTypeNorItsMessageIsSent(self) -> None:
        unexpected_exception: RuntimeError = RuntimeError(INTERNAL_FAILURE_DETAIL)
        scripted_asgi_server: ScriptedAsgiServer = ScriptedAsgiServer([{"type": "http.request", "body": b"", "more_body": False}])
        middleware_exception_translation: MiddlewareExceptionTranslation = MiddlewareExceptionTranslation(create_app_that_fails(unexpected_exception))
        expected_status_code: int = 500
        expected_exception_type_header: bytes = ExceptionToWireTranslator.UNEXPECTED_EXCEPTION_TYPE.encode("ascii")
        expected_internal_detail_is_sent: bool = False

        await middleware_exception_translation(create_http_scope(), scripted_asgi_server.receive, scripted_asgi_server.send)

        actual_response_start: Message = scripted_asgi_server.sent_messages[0]
        actual_response_body: Message = scripted_asgi_server.sent_messages[1]
        actual_header_value_by_name: dict[bytes, bytes] = dict(actual_response_start["headers"])
        assert (
            actual_response_start["status"],
            actual_header_value_by_name[b"exception-type"],
            INTERNAL_FAILURE_DETAIL in bytes(actual_response_body["body"]).decode("utf-8"),
        ) == (expected_status_code, expected_exception_type_header, expected_internal_detail_is_sent)
