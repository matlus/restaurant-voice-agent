import asyncio
from collections.abc import AsyncIterator, Iterable
from typing import Final

from voice_agent_conversation import ConversationEvent

# ConversationStarted, the greeting's speech and the end of the agent's greeting turn.
GREETING_EVENT_COUNT: Final[int] = 3


class GuestMicrophoneBreakdownException(Exception):
    """The guest's audio source broke, as a host's microphone or socket read might."""


class GuestMicrophone:
    """The guest's side of a call, played by the test: it speaks audio chunks, then hangs up or breaks.

    It notes when the domain has let go of its audio stream, whether the stream ended or the domain stopped reading it.
    """

    def __init__(self) -> None:
        self._spoken_chunks: asyncio.Queue[bytes | GuestMicrophoneBreakdownException | None] = asyncio.Queue()
        self.audio_stream_was_released: bool = False

    def speak(self, pcm_audio: bytes) -> None:
        self._spoken_chunks.put_nowait(pcm_audio)

    def hang_up(self) -> None:
        self._spoken_chunks.put_nowait(None)

    def break_down(self, guest_microphone_breakdown_exception: GuestMicrophoneBreakdownException) -> None:
        self._spoken_chunks.put_nowait(guest_microphone_breakdown_exception)

    async def stream_audio(self) -> AsyncIterator[bytes]:
        try:
            while (spoken_chunk := await self._spoken_chunks.get()) is not None:
                if isinstance(spoken_chunk, GuestMicrophoneBreakdownException):
                    raise spoken_chunk
                yield spoken_chunk
        finally:
            self.audio_stream_was_released = True

    async def take_part(
        self,
        conversation: AsyncIterator[ConversationEvent],
        guest_audio_chunks: Iterable[bytes],
        hang_up_after_event_count: int = GREETING_EVENT_COUNT,
        guest_microphone_breakdown_exception: GuestMicrophoneBreakdownException | None = None,
    ) -> list[ConversationEvent]:
        """Listens to the call and gathers its events. Once the agent's greeting is over the guest says each chunk;
        the guest hangs up after the given number of events, or the microphone breaks right after speaking if a breakdown is given."""
        actual_conversation_events: list[ConversationEvent] = []
        conversation_event: ConversationEvent
        async for conversation_event in conversation:
            actual_conversation_events.append(conversation_event)
            if len(actual_conversation_events) == GREETING_EVENT_COUNT:
                self._speak_chunks(guest_audio_chunks)
                if guest_microphone_breakdown_exception is not None:
                    self.break_down(guest_microphone_breakdown_exception)
            if guest_microphone_breakdown_exception is None and len(actual_conversation_events) == hang_up_after_event_count:
                self.hang_up()
        return actual_conversation_events

    def _speak_chunks(self, guest_audio_chunks: Iterable[bytes]) -> None:
        guest_audio_chunk: bytes
        for guest_audio_chunk in guest_audio_chunks:
            self.speak(guest_audio_chunk)
