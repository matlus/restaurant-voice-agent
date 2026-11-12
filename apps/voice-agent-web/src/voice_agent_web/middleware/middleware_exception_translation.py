import logging
from enum import Enum, auto

from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from voice_agent_conversation import VoiceAgentConversationBaseException, VoiceAgentConversationBusinessBaseException
from voice_agent_restaurant import VoiceAgentRestaurantBaseException, VoiceAgentRestaurantBusinessBaseException
from voice_agent_web.middleware.translators.exception_to_wire_translator import ExceptionToWireTranslator, WebSocketFailure


class ConnectionState(Enum):
    """How far one HTTP exchange or WebSocket connection has gone, as far as answering a failure is concerned."""

    AWAITING_RESPONSE = auto()  # Nothing sent yet: an HTTP response or a WebSocket handshake answer can still be sent.
    OPEN = auto()  # The HTTP response has started, or the WebSocket is accepted and still open.
    ENDED = auto()  # The app closed the WebSocket, or the client disconnected or stopped taking frames; nothing more can reach it.


class MiddlewareExceptionTranslation:
    """The one place an escaped exception is caught, logged once and told to the caller, for HTTP and WebSocket alike.

    Starlette's HTTP middleware does not see WebSocket connections, so this is a plain ASGI middleware. What the
    caller is told, envelope included, is ExceptionToWireTranslator's job; this shell only sends it, and only while
    the caller can still receive it.
    """

    def __init__(self, app: ASGIApp) -> None:
        self._app: ASGIApp = app
        self._logger: logging.Logger = logging.getLogger(__name__)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await self._app(scope, receive, send)
            return
        # Each connection's progress is an immutable state rebound in this call's own frame, so the one long-lived
        # middleware instance holds nothing about any connection.
        connection_state: ConnectionState = ConnectionState.AWAITING_RESPONSE

        async def receive_noting_progress() -> Message:
            nonlocal connection_state
            received_message: Message = await receive()
            connection_state = self._state_after_receiving(connection_state, received_message)
            return received_message

        async def send_noting_progress(sent_message: Message) -> None:
            nonlocal connection_state
            connection_state = self._state_after_sending(connection_state, sent_message)
            try:
                await send(sent_message)
            except OSError:
                # The server refuses a frame once the client has gone, before the app has read the disconnect.
                connection_state = ConnectionState.ENDED
                raise

        try:
            await self._app(scope, receive_noting_progress, send_noting_progress)
        except Exception as escaped_exception:  # noqa: BLE001 - the host boundary: every escaped failure is logged once and translated here
            self._log_exception(escaped_exception, scope)
            if scope["type"] == "websocket":
                await self._answer_websocket_failure(send, connection_state, escaped_exception)
            elif connection_state is ConnectionState.AWAITING_RESPONSE:
                await self._send_problem_details(scope, receive, send, escaped_exception)

    @staticmethod
    def _state_after_receiving(connection_state: ConnectionState, received_message: Message) -> ConnectionState:
        if received_message["type"] == "websocket.disconnect":
            return ConnectionState.ENDED
        return connection_state

    @staticmethod
    def _state_after_sending(connection_state: ConnectionState, sent_message: Message) -> ConnectionState:
        if sent_message["type"] in {"http.response.start", "websocket.accept"}:
            return ConnectionState.OPEN
        if sent_message["type"] == "websocket.close":
            return ConnectionState.ENDED
        return connection_state

    def _log_exception(self, escaped_exception: Exception, scope: Scope) -> None:
        request_description: str = f"{scope['type']} {scope['path']}"
        if isinstance(escaped_exception, VoiceAgentConversationBusinessBaseException | VoiceAgentRestaurantBusinessBaseException):
            # A business refusal is the caller's to act on, not a fault: a warning with its context and no traceback.
            escaped_exception.add_contextual_data({"Request": request_description})
            self._logger.warning(
                "Request refused: %s: %s",
                request_description,
                escaped_exception.message,
                extra={"event_fields": escaped_exception.contextual_data_by_name},
            )
        elif isinstance(escaped_exception, VoiceAgentConversationBaseException | VoiceAgentRestaurantBaseException):
            escaped_exception.add_contextual_data({"Request": request_description})
            self._logger.error("Request failed: %s\n%s", request_description, escaped_exception.to_string())
        else:
            self._logger.error("Request failed unexpectedly: %s", request_description, exc_info=escaped_exception)

    @classmethod
    async def _answer_websocket_failure(cls, send: Send, connection_state: ConnectionState, escaped_exception: Exception) -> None:
        # An ended connection has no one left to tell; the failure is in the log.
        if connection_state is ConnectionState.ENDED:
            return
        websocket_failure: WebSocketFailure = ExceptionToWireTranslator.translate_to_websocket_failure(escaped_exception)
        # Before the handshake is accepted a close frame is all the server can send: it refuses the handshake.
        if connection_state is ConnectionState.OPEN:
            await cls._send_websocket_error_message(send, websocket_failure)
        await cls._close_websocket(send, websocket_failure)

    @staticmethod
    async def _send_websocket_error_message(send: Send, websocket_failure: WebSocketFailure) -> None:
        await send({"type": "websocket.send", "text": websocket_failure.error_message_text})

    @staticmethod
    async def _close_websocket(send: Send, websocket_failure: WebSocketFailure) -> None:
        await send({"type": "websocket.close", "code": websocket_failure.close_code, "reason": websocket_failure.close_reason})

    @staticmethod
    async def _send_problem_details(scope: Scope, receive: Receive, send: Send, escaped_exception: Exception) -> None:
        problem_details_response: Response = ExceptionToWireTranslator.translate_to_problem_details(
            escaped_exception, request_path=str(scope["path"])
        )
        await problem_details_response(scope, receive, send)
