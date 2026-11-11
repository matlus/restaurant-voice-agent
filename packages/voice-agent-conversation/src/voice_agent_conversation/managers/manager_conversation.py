import asyncio
import contextlib
from collections.abc import AsyncGenerator, AsyncIterable
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
    AgentSpeechCutOff,
    AgentToolCallRequested,
    ConversationEvent,
    ConversationRequest,
    ConversationStarted,
    GuestSideEvent,
    GuestSpeechChunk,
    VoiceOption,
    VoiceSessionEvent,
    VoiceSessionSettings,
)
from voice_agent_conversation.managers.rules.agent_instructions import AgentInstructions
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
            yield ConversationStarted(audio_format=realtime_voice_session.audio_format, voice_option=voice_option)
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
        a failure on either side escapes."""
        guest_audio_ended: asyncio.Event = asyncio.Event()
        guest_audio_forwarding: asyncio.Task[None] = asyncio.create_task(
            ManagerConversation._forward_guest_side_events(guest_side_events, realtime_voice_session, guest_audio_ended)
        )
        # Wrong tool calls are counted per conversation; the toolbox ends the call when too many come in a row.
        consecutive_call_repair_count: int = 0
        try:
            voice_session_event: VoiceSessionEvent
            async for voice_session_event in realtime_voice_session.receive_events():
                if isinstance(voice_session_event, AgentToolCallRequested):
                    consecutive_call_repair_count = await ManagerConversation._answer_tool_call(
                        realtime_voice_session, agent_toolbox, voice_session_event, consecutive_call_repair_count, guest_audio_ended
                    )
                else:
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
        guest_side_events: AsyncIterable[GuestSideEvent], realtime_voice_session: RealtimeVoiceSessionBase, guest_audio_ended: asyncio.Event
    ) -> None:
        try:
            guest_side_event: GuestSideEvent
            async for guest_side_event in guest_side_events:
                match guest_side_event:
                    case GuestSpeechChunk(pcm_audio=pcm_audio):
                        await realtime_voice_session.send_guest_audio(pcm_audio)
                    case AgentSpeechCutOff(unplayed_milliseconds=unplayed_milliseconds):
                        await realtime_voice_session.cut_off_agent_speech(unplayed_milliseconds)
        finally:
            # The guest hung up or forwarding failed. Closing the session ends the event relay.
            guest_audio_ended.set()
            await realtime_voice_session.close()
