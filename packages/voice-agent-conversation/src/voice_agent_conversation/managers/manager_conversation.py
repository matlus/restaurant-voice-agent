import asyncio
import contextlib
from collections.abc import AsyncGenerator, AsyncIterable, Callable
from datetime import datetime
from types import TracebackType
from typing import Self

from voice_agent_conversation.managers.agent_tools.agent_toolbox import AgentToolbox, AgentToolCallAnswer
from voice_agent_conversation.managers.data_managers.data_manager_voice_catalog import DataManagerVoiceCatalog
from voice_agent_conversation.managers.exceptions.conversation_exceptions import LogEventConversation, VoiceNotOfferedException
from voice_agent_conversation.managers.gateways.realtime_voice_gateway_base import RealtimeVoiceGatewayBase, RealtimeVoiceSessionBase
from voice_agent_conversation.managers.gateways.realtime_voice_gateway_openai import RealtimeVoiceGatewayOpenAI
from voice_agent_conversation.managers.models.conversation_models import (
    AgentSessionEvent,
    AgentSpeechChunk,
    AgentSpeechCutOff,
    AgentSpeechPart,
    AgentSpeechReceived,
    AgentToolCallRequested,
    AgentTurnFinished,
    ConversationEvent,
    ConversationRequest,
    ConversationStarted,
    GuestSideEvent,
    GuestSpeechChunk,
    GuestStartedSpeaking,
    GuestStoppedSpeaking,
    SentAgentSpeech,
    VoiceOption,
    VoiceSessionEvent,
    VoiceSessionSettings,
)
from voice_agent_conversation.managers.rules.agent_instructions import AgentInstructions
from voice_agent_conversation.managers.rules.agent_speech_playback import AgentSpeechPlayback
from voice_agent_conversation.managers.service_locators.service_locator_base import ServiceLocatorBase
from voice_agent_conversation.managers.validators.validator_conversation_requests import ValidatorConversationRequests
from voice_agent_restaurant import DomainFacade as RestaurantDomainFacade, RestaurantProfile


class ManagerConversation:
    """Runs voice conversations: chooses the voice, briefs the agent, relays audio both ways and runs the tools the agent calls."""

    def __init__(self, service_locator: ServiceLocatorBase) -> None:
        self._restaurant_domain_facade: RestaurantDomainFacade = service_locator.create_restaurant_domain_facade()
        self._agent_toolbox: AgentToolbox = AgentToolbox(self._restaurant_domain_facade)
        self._realtime_voice_gateway: RealtimeVoiceGatewayBase = RealtimeVoiceGatewayOpenAI(
            service_locator.get_configuration_provider().get_openai_realtime_settings()
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None) -> None:
        await self.close()

    async def close(self) -> None:
        # Each close() is idempotent, so this one is too. Reverse order of creation.
        await self._realtime_voice_gateway.close()
        await self._restaurant_domain_facade.close()

    async def get_voice_options(self) -> list[VoiceOption]:
        return await asyncio.to_thread(DataManagerVoiceCatalog.get_voice_options)

    async def converse(
        self, conversation_request: ConversationRequest, guest_side_events: AsyncIterable[GuestSideEvent]
    ) -> AsyncGenerator[ConversationEvent]:
        voice_key: str = ValidatorConversationRequests.validate_conversation_request(conversation_request)
        voice_option: VoiceOption = await self._retrieve_voice_option(voice_key)
        restaurant_profile: RestaurantProfile = await self._restaurant_domain_facade.get_restaurant_profile()
        voice_session_settings: VoiceSessionSettings = VoiceSessionSettings(
            provider_voice_id=voice_option.provider_voice_id,
            agent_instructions=await self._compose_agent_instructions(restaurant_profile),
            agent_tool_definitions=self._agent_toolbox.get_tool_definitions(),
        )
        async with await self._realtime_voice_gateway.open_session(voice_session_settings) as realtime_voice_session:
            yield ConversationStarted(conversation_audio_format=realtime_voice_session.conversation_audio_format, voice_option=voice_option)
            await realtime_voice_session.request_greeting(AgentInstructions.compose_greeting(restaurant_profile.name))
            # Closing the relay here, in this task, settles guest side forwarding before the session closes.
            async with contextlib.aclosing(
                self._relay_conversation(realtime_voice_session, guest_side_events, self._agent_toolbox)
            ) as agent_session_events:
                agent_session_event: AgentSessionEvent
                async for agent_session_event in agent_session_events:
                    yield agent_session_event

    async def _retrieve_voice_option(self, voice_key: str) -> VoiceOption:
        voice_options: list[VoiceOption] = await self.get_voice_options()
        matching_voice_options: list[VoiceOption] = [voice_option for voice_option in voice_options if voice_option.voice_key == voice_key]
        if not matching_voice_options:
            raise VoiceNotOfferedException(
                requested_voice_key=voice_key,
                offered_voice_keys=[voice_option.voice_key for voice_option in voice_options],
                log_event=LogEventConversation.CONVERSATION_START,
            )
        return matching_voice_options[0]

    async def _compose_agent_instructions(self, restaurant_profile: RestaurantProfile) -> str:
        restaurant_local_now: datetime = await self._restaurant_domain_facade.get_restaurant_local_now()
        return AgentInstructions.compose(restaurant_profile.name, restaurant_local_now)

    @staticmethod
    async def _relay_conversation(
        realtime_voice_session: RealtimeVoiceSessionBase, guest_side_events: AsyncIterable[GuestSideEvent], agent_toolbox: AgentToolbox
    ) -> AsyncGenerator[AgentSessionEvent]:
        """Sends the guest side on while yielding the agent's events and answering its tool calls. Ends when either side does;
        a failure on either side escapes.

        A reply in which the agent calls tools ends without speech; it speaks once it has the answers. So when such a reply
        ends, the next reply is asked for instead of reporting the turn as finished, unless the guest is talking: the
        provider answers the guest by itself once they finish, and a reply asked for now would talk over them. The agent's
        speech is counted as it is passed on, so a cut-off report from the guest's side can tell the provider where the
        guest stopped hearing it.
        """
        guest_audio_ended: asyncio.Event = asyncio.Event()
        # Rebound as speech is passed on; the guest side forwarding reads the latest count through this frame.
        sent_agent_speech: SentAgentSpeech | None = None
        guest_audio_forwarding: asyncio.Task[None] = asyncio.create_task(
            ManagerConversation._forward_guest_side_events(guest_side_events, realtime_voice_session, guest_audio_ended, lambda: sent_agent_speech)
        )
        # Wrong tool calls are counted per conversation; the toolbox ends the call when too many come in a row.
        consecutive_call_repair_count: int = 0
        has_answered_tool_calls: bool = False
        guest_is_speaking: bool = False
        try:
            voice_session_event: VoiceSessionEvent
            async for voice_session_event in realtime_voice_session.receive_events():
                match voice_session_event:
                    case AgentToolCallRequested():
                        consecutive_call_repair_count = await ManagerConversation._answer_tool_call(
                            realtime_voice_session, agent_toolbox, voice_session_event, consecutive_call_repair_count, guest_audio_ended
                        )
                        has_answered_tool_calls = True
                    case AgentSpeechReceived(pcm_audio=pcm_audio):
                        sent_agent_speech = AgentSpeechPlayback.count_sent_agent_speech(sent_agent_speech, voice_session_event)
                        yield AgentSpeechChunk(pcm_audio=pcm_audio)
                    case AgentTurnFinished() if has_answered_tool_calls:
                        has_answered_tool_calls = False
                        # A guest who is talking gets the reply the provider starts by itself when they finish.
                        if not guest_is_speaking:
                            await ManagerConversation._request_next_reply(realtime_voice_session, guest_audio_ended)
                    case GuestStartedSpeaking():
                        guest_is_speaking = True
                        yield voice_session_event
                    case GuestStoppedSpeaking():
                        guest_is_speaking = False
                    case _:
                        yield voice_session_event
        finally:
            await ManagerConversation._settle_guest_audio_forwarding(guest_audio_forwarding, guest_audio_ended)

    @staticmethod
    async def _answer_tool_call(
        realtime_voice_session: RealtimeVoiceSessionBase,
        agent_toolbox: AgentToolbox,
        agent_tool_call_requested: AgentToolCallRequested,
        consecutive_call_repair_count: int,
        guest_audio_ended: asyncio.Event,
    ) -> int:
        """Runs the tool the agent asked for and sends the answer back, and returns how many wrong calls in a row now stand.
        A guest who hung up while the tool ran is not answered: the session is already closing."""
        agent_tool_call_answer: AgentToolCallAnswer = await agent_toolbox.run_tool_call(agent_tool_call_requested, consecutive_call_repair_count)
        if not guest_audio_ended.is_set():
            await realtime_voice_session.send_tool_result(agent_tool_call_requested.call_id, agent_tool_call_answer.tool_output_json)
        return agent_tool_call_answer.consecutive_call_repair_count

    @staticmethod
    async def _request_next_reply(realtime_voice_session: RealtimeVoiceSessionBase, guest_audio_ended: asyncio.Event) -> None:
        # A guest who hung up gets no next reply: the session is already closing.
        if not guest_audio_ended.is_set():
            await realtime_voice_session.request_next_reply()

    @staticmethod
    async def _settle_guest_audio_forwarding(guest_audio_forwarding: asyncio.Task[None], guest_audio_ended: asyncio.Event) -> None:
        # Once the guest audio has ended, forwarding is closing the session and finishes by itself; awaiting it
        # re-raises a forwarding failure. Before that it would wait for guest audio forever, so it is cancelled.
        if not guest_audio_ended.is_set():
            guest_audio_forwarding.cancel()
        try:
            await guest_audio_forwarding
        except asyncio.CancelledError:
            # Only the cancellation the relay requested ends here; one aimed at the task holding the call goes on.
            if ManagerConversation._is_current_task_being_cancelled():
                raise

    @staticmethod
    def _is_current_task_being_cancelled() -> bool:
        current_task: asyncio.Task[object] | None = asyncio.current_task()
        return current_task is not None and current_task.cancelling() > 0

    @staticmethod
    async def _forward_guest_side_events(
        guest_side_events: AsyncIterable[GuestSideEvent],
        realtime_voice_session: RealtimeVoiceSessionBase,
        guest_audio_ended: asyncio.Event,
        read_sent_agent_speech: Callable[[], SentAgentSpeech | None],
    ) -> None:
        # The part already cut off is remembered, so one part is cut off once however many reports follow.
        cut_off_agent_speech_part: AgentSpeechPart | None = None
        try:
            guest_side_event: GuestSideEvent
            async for guest_side_event in guest_side_events:
                match guest_side_event:
                    case GuestSpeechChunk(pcm_audio=pcm_audio):
                        await realtime_voice_session.send_guest_audio(pcm_audio)
                    case AgentSpeechCutOff():
                        cut_off_agent_speech_part = await ManagerConversation._cut_off_agent_speech(
                            realtime_voice_session, guest_side_event, read_sent_agent_speech(), cut_off_agent_speech_part
                        )
        finally:
            # The guest hung up or forwarding failed. Closing the session ends the event relay.
            guest_audio_ended.set()
            await realtime_voice_session.close()

    @staticmethod
    async def _cut_off_agent_speech(
        realtime_voice_session: RealtimeVoiceSessionBase,
        agent_speech_cut_off: AgentSpeechCutOff,
        sent_agent_speech: SentAgentSpeech | None,
        cut_off_agent_speech_part: AgentSpeechPart | None,
    ) -> AgentSpeechPart | None:
        """Returns the part cut off so far, which the caller hands back with the next report: a report that removes nothing
        the guest did not hear, or names a part already cut off, changes nothing."""
        if sent_agent_speech is None or not AgentSpeechPlayback.drops_unheard_speech(
            sent_agent_speech, agent_speech_cut_off, cut_off_agent_speech_part
        ):
            return cut_off_agent_speech_part
        heard_milliseconds: int = AgentSpeechPlayback.to_heard_milliseconds(
            sent_agent_speech,
            agent_speech_cut_off.unplayed_milliseconds,
            realtime_voice_session.conversation_audio_format.agent_audio_sample_rate_hz,
        )
        await realtime_voice_session.cut_off_agent_speech(sent_agent_speech.agent_speech_part, heard_milliseconds)
        return sent_agent_speech.agent_speech_part
