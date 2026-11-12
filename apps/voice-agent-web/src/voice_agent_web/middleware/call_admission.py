import asyncio
import json
from typing import Final

from starlette.types import ASGIApp, Receive, Scope, Send

from voice_agent_web.composers.composer_conversation_messages import ComposerConversationMessages

TRY_AGAIN_LATER_CLOSE_CODE: Final[int] = 1013


def create_call_admission(app: ASGIApp, maximum_concurrent_calls: int) -> ASGIApp:
    """Wraps the host so no more than maximum_concurrent_calls WebSocket calls run at once. Every call holds a paid speech
    provider session, so a caller beyond the limit is told all lines are busy and the socket closes with 1013.

    The count of running calls is process-wide state. It lives here, in the host's composition, held by the one call
    slot semaphore this function creates for the app it wraps, rather than in a class whose behavior other code relies on.
    """
    call_slots: asyncio.Semaphore = asyncio.Semaphore(maximum_concurrent_calls)

    async def admit_call(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "websocket":
            await app(scope, receive, send)
            return
        # Checking and taking a slot do not yield, so no other call can take the last slot in between.
        if call_slots.locked():
            await _refuse_busy_call(receive, send)
            return
        async with call_slots:
            await app(scope, receive, send)

    return admit_call


async def _refuse_busy_call(receive: Receive, send: Send) -> None:
    # The handshake is accepted so the page can be told why; a refused handshake would reach it only as a failure.
    await receive()
    await send({"type": "websocket.accept"})
    await send({"type": "websocket.send", "text": json.dumps(ComposerConversationMessages.compose_lines_busy_error())})
    await send({"type": "websocket.close", "code": TRY_AGAIN_LATER_CLOSE_CODE, "reason": ComposerConversationMessages.LINES_BUSY_TITLE})
