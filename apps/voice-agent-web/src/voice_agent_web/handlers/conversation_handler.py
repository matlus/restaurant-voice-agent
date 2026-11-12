import json
import logging
import time
from collections.abc import AsyncGenerator, AsyncIterable
from contextlib import aclosing

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import Message
from starlette.websockets import WebSocket, WebSocketState

from voice_agent_conversation import (
    AgentToolCallAnswered,
    ConversationEvent,
    ConversationRequest,
    DomainFacade,
    GuestSideEvent,
    SpeechProviderErrorTolerated,
    VoiceOption,
)
from voice_agent_web.composers.composer_call_summary import ComposerCallSummary
from voice_agent_web.composers.composer_conversation_messages import ComposerConversationMessages
from voice_agent_web.parsers.parser_conversation_request import ParserConversationRequest
from voice_agent_web.parsers.parser_guest_side_message import ParserGuestSideMessage
from voice_agent_web.resource_models.call_records import CallRecord
from voice_agent_web.resource_models.conversation_resources import ConversationMessage


class ConversationHandler:
    """The browser's two capabilities: list the voices, and hold a conversation over a WebSocket.

    Each method reads, parses, calls the domain through one Hook and composes the reply. Failures pass
    untouched to the exception translation middleware. A browser hanging up is the normal end of a call,
    not a failure: the guest audio stream ends at the disconnect, and nothing is sent once the browser is gone.
    A speech provider error the call carried on through is logged here, at the host boundary, and never sent to the page.
    Every call ends with one structured summary in the log, failed calls included; the failure itself is logged by the
    exception translation middleware.
    """

    def __init__(self, domain_facade: DomainFacade) -> None:
        self._domain_facade: DomainFacade = domain_facade
        self._logger: logging.Logger = logging.getLogger(__name__)

    async def check_health(self, _request: Request) -> Response:
        await self._check_readiness_through_domain()
        return JSONResponse(content={"status": "ok"})

    async def list_voices(self, _request: Request) -> Response:
        voice_options: list[VoiceOption] = await self._get_voice_options_through_domain()
        return JSONResponse(content=ComposerConversationMessages.compose_voices(voice_options))

    async def hold_conversation(self, websocket: WebSocket) -> None:
        conversation_request: ConversationRequest = ParserConversationRequest.parse(websocket.query_params)
        await websocket.accept()
        await self._hold_summarized_call(websocket, conversation_request)
        await self._close_browser_connection(websocket)

    async def _hold_summarized_call(self, websocket: WebSocket, conversation_request: ConversationRequest) -> None:
        """Relays the call and logs its summary when it ends, however it ends."""
        call_started_at: float = time.monotonic()
        # Rebound as events arrive, so the summary in the finally block sees how far the call got even when it fails.
        call_record: CallRecord = ComposerCallSummary.start_call_record(conversation_request.voice_key)
        call_failed: bool = True
        try:
            async with aclosing(self._relay_conversation_events(websocket, conversation_request, call_record)) as call_record_updates:
                call_record_update: CallRecord
                async for call_record_update in call_record_updates:
                    call_record = call_record_update
            call_failed = False
        finally:
            self._log_call_summary(call_record, time.monotonic() - call_started_at, call_failed=call_failed)

    async def _relay_conversation_events(
        self, websocket: WebSocket, conversation_request: ConversationRequest, call_record: CallRecord
    ) -> AsyncGenerator[CallRecord]:
        """Relays each conversation event to the browser, yielding the call record updated by it first, so a relay that
        fails still leaves the event recorded."""
        async with aclosing(self._converse_through_domain(conversation_request, self._receive_guest_side_events(websocket))) as conversation:
            conversation_event: ConversationEvent
            async for conversation_event in conversation:
                call_record = ComposerCallSummary.record_event(call_record, conversation_event)
                yield call_record
                await self._relay_event_to_browser(websocket, conversation_event)

    async def _check_readiness_through_domain(self) -> None:
        await self._domain_facade.check_readiness()

    async def _get_voice_options_through_domain(self) -> list[VoiceOption]:
        return await self._domain_facade.get_voice_options()

    def _converse_through_domain(
        self, conversation_request: ConversationRequest, guest_side_events: AsyncIterable[GuestSideEvent]
    ) -> AsyncGenerator[ConversationEvent]:
        return self._domain_facade.converse(conversation_request, guest_side_events)

    async def _relay_event_to_browser(self, websocket: WebSocket, conversation_event: ConversationEvent) -> None:
        match conversation_event:
            case SpeechProviderErrorTolerated():
                self._log_tolerated_provider_error(conversation_event)
            case AgentToolCallAnswered():
                # Recorded for the call's summary; the page has nothing to show for it.
                pass
            case _:
                # After the guest hangs up the conversation winds down; there is no one left to send to.
                if self._is_browser_connected(websocket):
                    await self._send_conversation_message(websocket, ComposerConversationMessages.compose_event(conversation_event))

    def _log_call_summary(self, call_record: CallRecord, call_seconds: float, *, call_failed: bool) -> None:
        self._logger.info(
            "Call ended",
            extra={"event_fields": ComposerCallSummary.compose_call_summary(call_record, call_seconds, call_failed=call_failed)},
        )

    def _log_tolerated_provider_error(self, speech_provider_error_tolerated: SpeechProviderErrorTolerated) -> None:
        self._logger.warning(
            "The speech provider reported an error the call carried on through: type=%s code=%s message=%s",
            speech_provider_error_tolerated.error_type,
            speech_provider_error_tolerated.error_code,
            speech_provider_error_tolerated.error_message,
        )

    @classmethod
    async def _close_browser_connection(cls, websocket: WebSocket) -> None:
        if cls._is_browser_connected(websocket):
            await cls._send_to_browser(websocket, {"type": "websocket.close", "code": 1000})

    @staticmethod
    def _is_browser_connected(websocket: WebSocket) -> bool:
        return websocket.client_state is WebSocketState.CONNECTED and websocket.application_state is WebSocketState.CONNECTED

    @staticmethod
    async def _receive_guest_side_events(websocket: WebSocket) -> AsyncGenerator[GuestSideEvent]:
        while True:
            websocket_message: Message = await websocket.receive()
            if websocket_message["type"] == "websocket.disconnect":
                return
            guest_side_event: GuestSideEvent | None = ParserGuestSideMessage.parse(websocket_message)
            if guest_side_event is not None:
                yield guest_side_event

    @classmethod
    async def _send_conversation_message(cls, websocket: WebSocket, conversation_message: ConversationMessage) -> None:
        if isinstance(conversation_message, bytes):
            await cls._send_to_browser(websocket, {"type": "websocket.send", "bytes": conversation_message})
        else:
            await cls._send_to_browser(websocket, {"type": "websocket.send", "text": json.dumps(conversation_message)})

    @staticmethod
    async def _send_to_browser(websocket: WebSocket, websocket_message: Message) -> None:
        await websocket.send(websocket_message)
