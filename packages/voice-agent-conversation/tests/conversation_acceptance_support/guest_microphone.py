import asyncio
from collections.abc import AsyncIterator, Iterable
from typing import Final

from voice_agent_conversation import AgentSpeechCutOff, ConversationEvent, GuestSideEvent, GuestSpeechChunk, GuestStartedSpeaking

# ConversationStarted, the greeting's speech and the end of the agent's greeting turn.
GREETING_EVENT_COUNT: Final[int] = 3


class GuestMicrophoneBreakdownException(Exception):
    """The guest's audio source broke, as a host's microphone or socket read might."""


class GuestMicrophone:
    """The guest's side of a call, played by the test: it speaks audio chunks, then hangs up or breaks. When the guest
    talks over the agent it can report agent speech cut off unplayed, as a host's page does.

    It notes when the domain has let go of its audio stream, whether the stream ended or the domain stopped reading it.
    """

    def __init__(self) -> None:
        self._guest_side_events: asyncio.Queue[GuestSideEvent | GuestMicrophoneBreakdownException | None] = asyncio.Queue()
        self.audio_stream_was_released: bool = False

    def speak(self, pcm_audio: bytes) -> None:
        self._guest_side_events.put_nowait(GuestSpeechChunk(pcm_audio=pcm_audio))

    def cut_off_agent_speech(self, unplayed_milliseconds: int) -> None:
        self._guest_side_events.put_nowait(AgentSpeechCutOff(unplayed_milliseconds=unplayed_milliseconds))

    def hang_up(self) -> None:
        self._guest_side_events.put_nowait(None)

    def break_down(self, guest_microphone_breakdown_exception: GuestMicrophoneBreakdownException) -> None:
        self._guest_side_events.put_nowait(guest_microphone_breakdown_exception)

    async def stream_guest_side_events(self) -> AsyncIterator[GuestSideEvent]:
        try:
            while (guest_side_event := await self._guest_side_events.get()) is not None:
                if isinstance(guest_side_event, GuestMicrophoneBreakdownException):
                    raise guest_side_event
                yield guest_side_event
        finally:
            self.audio_stream_was_released = True

    async def take_part(
        self,
        conversation: AsyncIterator[ConversationEvent],
        guest_audio_chunks: Iterable[bytes],
        hang_up_after_event_count: int = GREETING_EVENT_COUNT,
        guest_microphone_breakdown_exception: GuestMicrophoneBreakdownException | None = None,
        unplayed_milliseconds_when_talked_over: int | None = None,
    ) -> list[ConversationEvent]:
        """Listens to the call and gathers its events. Once the agent's greeting is over the guest says each chunk;
        the guest hangs up after the given number of events, or the microphone breaks right after speaking if a breakdown is given.
        Given an unplayed duration, the guest's side reports that much agent speech cut off each time the guest talks over the agent."""
        actual_conversation_events: list[ConversationEvent] = []
        conversation_event: ConversationEvent
        async for conversation_event in conversation:
            actual_conversation_events.append(conversation_event)
            if isinstance(conversation_event, GuestStartedSpeaking) and unplayed_milliseconds_when_talked_over is not None:
                self.cut_off_agent_speech(unplayed_milliseconds_when_talked_over)
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
