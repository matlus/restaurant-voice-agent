import json
from collections.abc import AsyncGenerator, AsyncIterable, AsyncIterator
from contextlib import aclosing

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import Message
from starlette.websockets import WebSocket, WebSocketState

from voice_agent_conversation import ConversationEvent, ConversationRequest, DomainFacade, VoiceOption
from voice_agent_web.composers.composer_conversation_messages import ComposerConversationMessages
from voice_agent_web.parsers.parser_conversation_request import ParserConversationRequest
from voice_agent_web.resource_models.conversation_resources import ConversationMessage


class ConversationHandler:
    """The browser's two capabilities: list the voices, and hold a conversation over a WebSocket.

    Each method reads, parses, calls the domain through one Hook and composes the reply. Failures pass
    untouched to the exception translation middleware. A browser hanging up is the normal end of a call,
    not a failure: the guest audio stream ends at the disconnect, and nothing is sent once the browser is gone.
    """

    def __init__(self, domain_facade: DomainFacade) -> None:
        self._domain_facade: DomainFacade = domain_facade

    async def list_voices(self, _request: Request) -> Response:
        voice_options: list[VoiceOption] = await self._get_voice_options_through_domain()
        return JSONResponse(content=ComposerConversationMessages.compose_voices(voice_options))

    async def hold_conversation(self, websocket: WebSocket) -> None:
        conversation_request: ConversationRequest = ParserConversationRequest.parse(websocket.query_params)
        await websocket.accept()
        async with aclosing(self._converse_through_domain(conversation_request, self._receive_guest_audio(websocket))) as conversation:
            await self._relay_conversation_to_browser(websocket, conversation)
        await self._close_browser_connection(websocket)

    async def _get_voice_options_through_domain(self) -> list[VoiceOption]:
        return await self._domain_facade.get_voice_options()

    def _converse_through_domain(
        self, conversation_request: ConversationRequest, guest_audio: AsyncIterable[bytes]
    ) -> AsyncGenerator[ConversationEvent]:
        return self._domain_facade.converse(conversation_request, guest_audio)

    @classmethod
    async def _relay_conversation_to_browser(cls, websocket: WebSocket, conversation: AsyncIterator[ConversationEvent]) -> None:
        conversation_event: ConversationEvent
        async for conversation_event in conversation:
            # After the guest hangs up the conversation winds down; there is no one left to send to.
            if cls._is_browser_connected(websocket):
                await cls._send_conversation_message(websocket, ComposerConversationMessages.compose_event(conversation_event))

    @classmethod
    async def _close_browser_connection(cls, websocket: WebSocket) -> None:
        if cls._is_browser_connected(websocket):
            await cls._send_to_browser(websocket, {"type": "websocket.close", "code": 1000})

    @staticmethod
    def _is_browser_connected(websocket: WebSocket) -> bool:
        return websocket.client_state is WebSocketState.CONNECTED and websocket.application_state is WebSocketState.CONNECTED

    @staticmethod
    async def _receive_guest_audio(websocket: WebSocket) -> AsyncGenerator[bytes]:
        """Yields each binary frame of guest audio until the browser hangs up. Text frames carry nothing the call needs."""
        while True:
            websocket_message: Message = await websocket.receive()
            if websocket_message["type"] == "websocket.disconnect":
                return
            guest_audio: bytes | None = websocket_message.get("bytes")
            if guest_audio:
                yield guest_audio

    @classmethod
    async def _send_conversation_message(cls, websocket: WebSocket, conversation_message: ConversationMessage) -> None:
        if isinstance(conversation_message, bytes):
            await cls._send_to_browser(websocket, {"type": "websocket.send", "bytes": conversation_message})
        else:
            await cls._send_to_browser(websocket, {"type": "websocket.send", "text": json.dumps(conversation_message)})

    @staticmethod
    async def _send_to_browser(websocket: WebSocket, websocket_message: Message) -> None:
        await websocket.send(websocket_message)
