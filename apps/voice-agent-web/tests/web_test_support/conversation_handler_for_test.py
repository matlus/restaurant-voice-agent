from collections.abc import AsyncGenerator, AsyncIterable, Sequence
from enum import Enum, auto
from typing import cast, final, override

from voice_agent_conversation import ConversationEvent, ConversationRequest, DomainFacade, GuestSideEvent, VoiceOption
from voice_agent_web.handlers.conversation_handler import ConversationHandler


class GuestAudioReading(Enum):
    """When a scripted conversation reads what the handler forwards from the guest's side, relative to yielding its events."""

    NOT_READ = auto()
    READ_AFTER_THE_EVENTS = auto()
    READ_BEFORE_THE_EVENTS = auto()


@final
class ConversationHandlerForTest(ConversationHandler):
    """Overrides the handler's domain Hooks, so handler tests run only what the handler owns: reading the request
    or socket, converting it for the domain, and composing what goes back. No domain sits beneath it.

    It captures what reached each Hook and answers as scripted. A scripted conversation yields its events and, as
    asked, reads what the handler forwards from the guest's side until the browser hangs up, before or after those events. A
    scripted failure is raised at the conversation Hook once the events are yielded, as a failing domain would.
    """

    def __init__(
        self,
        *,
        scripted_voice_options: Sequence[VoiceOption] = (),
        scripted_conversation_events: Sequence[ConversationEvent] = (),
        guest_audio_reading: GuestAudioReading = GuestAudioReading.NOT_READ,
        scripted_conversation_failure: Exception | None = None,
    ) -> None:
        # The Hooks never delegate, so no facade is ever needed.
        super().__init__(domain_facade=cast(DomainFacade, None))
        self._scripted_voice_options: tuple[VoiceOption, ...] = tuple(scripted_voice_options)
        self._scripted_conversation_events: tuple[ConversationEvent, ...] = tuple(scripted_conversation_events)
        self._guest_audio_reading: GuestAudioReading = guest_audio_reading
        self._scripted_conversation_failure: Exception | None = scripted_conversation_failure
        self.captured_conversation_request: ConversationRequest | None = None
        self.captured_guest_side_events: list[GuestSideEvent] = []
        self.captured_readiness_check_count: int = 0

    @override
    async def _check_readiness_through_domain(self) -> None:
        self.captured_readiness_check_count += 1

    @override
    async def _get_voice_options_through_domain(self) -> list[VoiceOption]:
        return list(self._scripted_voice_options)

    @override
    def _converse_through_domain(
        self, conversation_request: ConversationRequest, guest_side_events: AsyncIterable[GuestSideEvent]
    ) -> AsyncGenerator[ConversationEvent]:
        self.captured_conversation_request = conversation_request
        return self._converse_as_scripted(guest_side_events)

    async def _converse_as_scripted(self, guest_side_events: AsyncIterable[GuestSideEvent]) -> AsyncGenerator[ConversationEvent]:
        if self._guest_audio_reading is GuestAudioReading.READ_BEFORE_THE_EVENTS:
            await self._capture_guest_side_events(guest_side_events)
        scripted_conversation_event: ConversationEvent
        for scripted_conversation_event in self._scripted_conversation_events:
            yield scripted_conversation_event
        if self._scripted_conversation_failure is not None:
            raise self._scripted_conversation_failure
        if self._guest_audio_reading is GuestAudioReading.READ_AFTER_THE_EVENTS:
            await self._capture_guest_side_events(guest_side_events)

    async def _capture_guest_side_events(self, guest_side_events: AsyncIterable[GuestSideEvent]) -> None:
        guest_side_event: GuestSideEvent
        async for guest_side_event in guest_side_events:
            self.captured_guest_side_events.append(guest_side_event)
