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
    AgentToolCallRequested,
    ConversationEvent,
    ConversationRequest,
    ConversationStarted,
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

    async def converse(self, conversation_request: ConversationRequest, guest_audio: AsyncIterable[bytes]) -> AsyncGenerator[ConversationEvent]:
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
            # Closing the relay here, in this task, settles guest audio forwarding before the session closes.
            async with contextlib.aclosing(
                self._relay_conversation(realtime_voice_session, guest_audio, self._agent_toolbox)
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
        realtime_voice_session: RealtimeVoiceSessionBase, guest_audio: AsyncIterable[bytes], agent_toolbox: AgentToolbox
    ) -> AsyncGenerator[AgentSessionEvent]:
        """Sends guest audio while yielding the agent's events and answering its tool calls. Ends when either side does;
        a failure on either side escapes."""
        guest_audio_ended: asyncio.Event = asyncio.Event()
        guest_audio_forwarding: asyncio.Task[None] = asyncio.create_task(
            ManagerConversation._forward_guest_audio(guest_audio, realtime_voice_session, guest_audio_ended)
        )
        # Wrong tool calls are counted per conversation; the toolbox ends the call when too many come in a row.
        consecutive_call_repair_count: int = 0
        try:
            session_event: VoiceSessionEvent
            async for session_event in realtime_voice_session.receive_events():
                if isinstance(session_event, AgentToolCallRequested):
                    agent_tool_call_answer: AgentToolCallAnswer = await agent_toolbox.run_tool_call(session_event, consecutive_call_repair_count)
                    consecutive_call_repair_count = agent_tool_call_answer.consecutive_call_repair_count
                    await realtime_voice_session.send_tool_result(session_event.call_id, agent_tool_call_answer.tool_output_json)
                else:
                    yield session_event
        finally:
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
    async def _forward_guest_audio(
        guest_audio: AsyncIterable[bytes], realtime_voice_session: RealtimeVoiceSessionBase, guest_audio_ended: asyncio.Event
    ) -> None:
        try:
            pcm_audio: bytes
            async for pcm_audio in guest_audio:
                await realtime_voice_session.send_guest_audio(pcm_audio)
        finally:
            # The guest hung up or forwarding failed. Closing the session ends the event relay.
            guest_audio_ended.set()
            await realtime_voice_session.close()
