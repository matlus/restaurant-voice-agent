import asyncio
import contextlib
import uuid
from collections.abc import AsyncGenerator, AsyncIterable, Callable
from datetime import datetime
from types import TracebackType
from typing import Final, Self

from voice_agent_conversation.managers.agent_tools.agent_toolbox import AgentToolbox, AgentToolCallAnswer
from voice_agent_conversation.managers.configuration_providers.configuration_provider import ConfigurationProvider
from voice_agent_conversation.managers.configuration_providers.settings_models.call_limit_settings import CallLimitSettings
from voice_agent_conversation.managers.data_managers.data_manager_voice_catalog import DataManagerVoiceCatalog
from voice_agent_conversation.managers.exceptions.conversation_exceptions import LogEventConversation, VoiceNotOfferedException
from voice_agent_conversation.managers.exceptions.voice_agent_conversation_exceptions import VoiceAgentConversationBaseException
from voice_agent_conversation.managers.gateways.realtime_voice_gateway_base import RealtimeVoiceGatewayBase, RealtimeVoiceSessionBase
from voice_agent_conversation.managers.gateways.realtime_voice_gateway_openai import RealtimeVoiceGatewayOpenAI
from voice_agent_conversation.managers.models.conversation_models import (
    AgentSessionEvent,
    AgentSpeechChunk,
    AgentSpeechCutOff,
    AgentSpeechPart,
    AgentSpeechReceived,
    AgentToolCallAnswered,
    AgentToolCallRequested,
    AgentTurnFinished,
    CallEndSignals,
    CallLimit,
    CallLimitReached,
    ConversationEvent,
    ConversationRequest,
    ConversationStarted,
    GuestAudioAllowance,
    GuestSideEvent,
    GuestSpeechActivity,
    GuestSpeechChunk,
    GuestStartedSpeaking,
    GuestStoppedSpeaking,
    SentAgentSpeech,
    SpeechProviderErrorTolerated,
    VoiceOption,
    VoiceSessionEvent,
    VoiceSessionSettings,
)
from voice_agent_conversation.managers.rules.agent_instructions import AgentInstructions
from voice_agent_conversation.managers.rules.agent_speech_playback import AgentSpeechPlayback
from voice_agent_conversation.managers.rules.call_limits import CallLimits
from voice_agent_conversation.managers.rules.guest_audio_pacing import GuestAudioPacing
from voice_agent_conversation.managers.service_locators.service_locator_base import ServiceLocatorBase
from voice_agent_conversation.managers.validators.validator_conversation_requests import ValidatorConversationRequests
from voice_agent_restaurant import DomainFacade as RestaurantDomainFacade, RestaurantProfile, VoiceAgentRestaurantBaseException


class ManagerConversation:
    """Runs voice conversations: chooses the voice, briefs the agent, relays audio both ways and runs the tools the agent calls.

    Every call holds a paid speech provider session, so each call ends with a spoken goodbye once it runs too long or the
    guest goes quiet for too long. How many calls run at once is the host's to bound: it is process-wide state, which no
    behavior class here holds.
    """

    CONVERSATION_ID_CONTEXT_KEY: Final[str] = "Conversation.Id"

    def __init__(self, service_locator: ServiceLocatorBase) -> None:
        configuration_provider: ConfigurationProvider = service_locator.get_configuration_provider()
        self._restaurant_domain_facade: RestaurantDomainFacade = service_locator.create_restaurant_domain_facade()
        self._agent_toolbox: AgentToolbox = AgentToolbox(self._restaurant_domain_facade)
        self._realtime_voice_gateway: RealtimeVoiceGatewayBase = RealtimeVoiceGatewayOpenAI(configuration_provider.get_openai_realtime_settings())
        self._call_limit_settings: CallLimitSettings = configuration_provider.get_call_limit_settings()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None) -> None:
        await self.close()

    async def close(self) -> None:
        # Each close() is idempotent, so this one is too. Reverse order of creation.
        await self._realtime_voice_gateway.close()
        await self._restaurant_domain_facade.close()

    async def check_readiness(self) -> None:
        """Reads the restaurant's store, so a host's health check fails when calls could not be held."""
        await self._restaurant_domain_facade.get_restaurant_profile()

    async def get_voice_options(self) -> list[VoiceOption]:
        return await asyncio.to_thread(DataManagerVoiceCatalog.get_voice_options)

    async def converse(
        self, conversation_request: ConversationRequest, guest_side_events: AsyncIterable[GuestSideEvent]
    ) -> AsyncGenerator[ConversationEvent]:
        voice_key: str = ValidatorConversationRequests.validate_conversation_request(conversation_request)
        conversation_id: str = uuid.uuid4().hex
        try:
            voice_option: VoiceOption = await self._retrieve_voice_option(voice_key)
            restaurant_profile: RestaurantProfile = await self._restaurant_domain_facade.get_restaurant_profile()
            voice_session_settings: VoiceSessionSettings = VoiceSessionSettings(
                provider_voice_id=voice_option.provider_voice_id,
                agent_instructions=await self._compose_agent_instructions(restaurant_profile.name),
                agent_tool_definitions=self._agent_toolbox.get_tool_definitions(),
            )
            async with await self._realtime_voice_gateway.open_session(voice_session_settings) as realtime_voice_session:
                yield ConversationStarted(
                    conversation_id=conversation_id,
                    conversation_audio_format=realtime_voice_session.conversation_audio_format,
                    voice_option=voice_option,
                )
                await realtime_voice_session.request_greeting(AgentInstructions.compose_greeting(restaurant_profile.name))
                # Closing the relay here, in this task, settles guest side forwarding before the session closes.
                async with contextlib.aclosing(
                    self._relay_conversation(realtime_voice_session, guest_side_events, self._agent_toolbox, self._call_limit_settings)
                ) as agent_session_events:
                    agent_session_event: AgentSessionEvent
                    async for agent_session_event in agent_session_events:
                        yield agent_session_event
        except (VoiceAgentConversationBaseException, VoiceAgentRestaurantBaseException) as domain_exception:
            # Ties the failure to this conversation in the host's log; the exception itself passes on unchanged.
            domain_exception.add_contextual_data({self.CONVERSATION_ID_CONTEXT_KEY: conversation_id})
            raise

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

    async def _compose_agent_instructions(self, restaurant_name: str) -> str:
        restaurant_local_now: datetime = await self._restaurant_domain_facade.get_restaurant_local_now()
        return AgentInstructions.compose(restaurant_name, restaurant_local_now)

    @staticmethod
    async def _relay_conversation(
        realtime_voice_session: RealtimeVoiceSessionBase,
        guest_side_events: AsyncIterable[GuestSideEvent],
        agent_toolbox: AgentToolbox,
        call_limit_settings: CallLimitSettings,
    ) -> AsyncGenerator[AgentSessionEvent]:
        """Sends the guest side on while yielding the agent's events and answering its tool calls. Ends when either side does;
        a failure on either side escapes.

        A reply in which the agent calls tools ends without speech; it speaks once it has the answers. So when such a reply
        ends, the next reply is asked for instead of reporting the turn as finished, unless the guest is talking: the
        provider answers the guest by itself once they finish, and a reply asked for now would talk over them. The agent's
        speech is counted as it is passed on, so a cut-off report from the guest's side can tell the provider where the
        guest stopped hearing it.

        Once a call limit is reached and the farewell asked for, the end of the farewell's own reply ends the call with
        CallLimitReached; the end of an earlier reply that arrives late does not. A farewell the provider refuses, because a
        reply was under way, is asked for again once that reply ends.
        """
        call_end_signals: CallEndSignals = ManagerConversation._create_call_end_signals()
        # Rebound as speech is passed on and as the guest starts and stops talking; the tasks below read the latest
        # value through this frame.
        sent_agent_speech: SentAgentSpeech | None = None
        guest_speech_activity: GuestSpeechActivity = ManagerConversation._observe_guest_speech_activity(guest_is_speaking=False)
        guest_audio_forwarding: asyncio.Task[None] = ManagerConversation._start_guest_side_forwarding(
            guest_side_events, realtime_voice_session, call_end_signals, lambda: sent_agent_speech
        )
        call_limit_enforcement: asyncio.Task[None] = ManagerConversation._start_call_limit_enforcement(
            realtime_voice_session, call_limit_settings, call_end_signals, lambda: guest_speech_activity
        )
        # Wrong tool calls are counted per conversation; the toolbox ends the call when too many come in a row.
        consecutive_call_repair_count: int = 0
        has_answered_tool_calls: bool = False
        farewell_was_refused: bool = False
        try:
            voice_session_event: VoiceSessionEvent
            async for voice_session_event in realtime_voice_session.receive_events():
                match voice_session_event:
                    case SpeechProviderErrorTolerated(refused_farewell=True):
                        farewell_was_refused = True
                        yield voice_session_event
                    case AgentTurnFinished(ended_farewell=True):
                        yield voice_session_event
                        break
                    case AgentTurnFinished() if call_end_signals.reached_call_limit.done():
                        # Some other reply ended after the limit; a farewell it held up is asked for again now.
                        yield voice_session_event
                        if farewell_was_refused:
                            farewell_was_refused = False
                            await ManagerConversation._request_farewell(
                                realtime_voice_session, call_end_signals.reached_call_limit.result(), call_end_signals.guest_audio_ended
                            )
                    case AgentToolCallRequested(tool_name=tool_name):
                        agent_tool_call_answer: AgentToolCallAnswer = await ManagerConversation._answer_tool_call(
                            realtime_voice_session,
                            agent_toolbox,
                            voice_session_event,
                            consecutive_call_repair_count,
                            call_end_signals.guest_audio_ended,
                        )
                        consecutive_call_repair_count = agent_tool_call_answer.consecutive_call_repair_count
                        has_answered_tool_calls = True
                        yield AgentToolCallAnswered(tool_name=tool_name, agent_tool_call_outcome=agent_tool_call_answer.agent_tool_call_outcome)
                    case AgentSpeechReceived(pcm_audio=pcm_audio):
                        sent_agent_speech = AgentSpeechPlayback.count_sent_agent_speech(sent_agent_speech, voice_session_event)
                        yield AgentSpeechChunk(pcm_audio=pcm_audio)
                    case AgentTurnFinished() if has_answered_tool_calls:
                        has_answered_tool_calls = False
                        # A guest who is talking gets the reply the provider starts by itself when they finish.
                        if not guest_speech_activity.guest_is_speaking:
                            await ManagerConversation._request_next_reply(realtime_voice_session, call_end_signals.guest_audio_ended)
                    case GuestStartedSpeaking():
                        guest_speech_activity = ManagerConversation._observe_guest_speech_activity(guest_is_speaking=True)
                        yield voice_session_event
                    case GuestStoppedSpeaking():
                        guest_speech_activity = ManagerConversation._observe_guest_speech_activity(guest_is_speaking=False)
                    case _:
                        yield voice_session_event
            # Reached after the farewell finished, or after enforcement closed a session whose farewell never came.
            if call_end_signals.reached_call_limit.done():
                yield CallLimitReached(call_limit=call_end_signals.reached_call_limit.result())
        finally:
            # Nested, so a failure settling the first task still settles the second and none outlives the call.
            try:
                await ManagerConversation._settle_call_limit_enforcement(call_limit_enforcement)
            finally:
                await ManagerConversation._settle_guest_audio_forwarding(guest_audio_forwarding, call_end_signals.guest_audio_ended)

    @staticmethod
    def _observe_guest_speech_activity(*, guest_is_speaking: bool) -> GuestSpeechActivity:
        # Read on the event loop's clock, the one the call limit enforcement measures against.
        return GuestSpeechActivity(guest_is_speaking=guest_is_speaking, last_heard_at=asyncio.get_running_loop().time())

    @staticmethod
    def _create_call_end_signals() -> CallEndSignals:
        return CallEndSignals(guest_audio_ended=asyncio.Event(), reached_call_limit=asyncio.get_running_loop().create_future())

    @staticmethod
    def _start_guest_side_forwarding(
        guest_side_events: AsyncIterable[GuestSideEvent],
        realtime_voice_session: RealtimeVoiceSessionBase,
        call_end_signals: CallEndSignals,
        read_sent_agent_speech: Callable[[], SentAgentSpeech | None],
    ) -> asyncio.Task[None]:
        return asyncio.create_task(
            ManagerConversation._forward_guest_side_events(guest_side_events, realtime_voice_session, call_end_signals, read_sent_agent_speech)
        )

    @staticmethod
    def _start_call_limit_enforcement(
        realtime_voice_session: RealtimeVoiceSessionBase,
        call_limit_settings: CallLimitSettings,
        call_end_signals: CallEndSignals,
        read_guest_speech_activity: Callable[[], GuestSpeechActivity],
    ) -> asyncio.Task[None]:
        return asyncio.create_task(
            ManagerConversation._enforce_call_limits(realtime_voice_session, call_limit_settings, call_end_signals, read_guest_speech_activity)
        )

    @staticmethod
    async def _answer_tool_call(
        realtime_voice_session: RealtimeVoiceSessionBase,
        agent_toolbox: AgentToolbox,
        agent_tool_call_requested: AgentToolCallRequested,
        consecutive_call_repair_count: int,
        guest_audio_ended: asyncio.Event,
    ) -> AgentToolCallAnswer:
        """Runs the tool the agent asked for and sends the answer back. A guest who hung up while the tool ran is not
        answered: the session is already closing."""
        agent_tool_call_answer: AgentToolCallAnswer = await agent_toolbox.run_tool_call(agent_tool_call_requested, consecutive_call_repair_count)
        if not guest_audio_ended.is_set():
            await realtime_voice_session.send_tool_result(agent_tool_call_requested.call_id, agent_tool_call_answer.tool_output_json)
        return agent_tool_call_answer

    @staticmethod
    async def _request_next_reply(realtime_voice_session: RealtimeVoiceSessionBase, guest_audio_ended: asyncio.Event) -> None:
        # A guest who hung up gets no next reply: the session is already closing.
        if not guest_audio_ended.is_set():
            await realtime_voice_session.request_next_reply()

    @staticmethod
    async def _enforce_call_limits(
        realtime_voice_session: RealtimeVoiceSessionBase,
        call_limit_settings: CallLimitSettings,
        call_end_signals: CallEndSignals,
        read_guest_speech_activity: Callable[[], GuestSpeechActivity],
    ) -> None:
        """Waits for a call limit, asks for the farewell and reports the limit. A farewell that never finishes would hold
        the paid session open, so the session is closed after a grace period and the call still ends."""
        call_limit: CallLimit = await ManagerConversation._wait_for_call_limit(call_limit_settings, read_guest_speech_activity)
        # A guest who hung up gets no farewell: the session is already closing.
        if call_end_signals.guest_audio_ended.is_set():
            return
        await ManagerConversation._request_farewell(realtime_voice_session, call_limit, call_end_signals.guest_audio_ended)
        call_end_signals.reached_call_limit.set_result(call_limit)
        await asyncio.sleep(CallLimits.FAREWELL_GRACE_SECONDS)
        await realtime_voice_session.close()

    @staticmethod
    async def _request_farewell(realtime_voice_session: RealtimeVoiceSessionBase, call_limit: CallLimit, guest_audio_ended: asyncio.Event) -> None:
        # A guest who hung up gets no farewell: the session is already closing.
        if not guest_audio_ended.is_set():
            await realtime_voice_session.request_farewell(AgentInstructions.compose_farewell(call_limit))

    @staticmethod
    async def _wait_for_call_limit(
        call_limit_settings: CallLimitSettings, read_guest_speech_activity: Callable[[], GuestSpeechActivity]
    ) -> CallLimit:
        event_loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        call_started_at: float = event_loop.time()
        # The wait is recomputed after every sleep: the guest may have spoken meanwhile, which moves the silence limit.
        call_limit: CallLimit | None
        while True:
            call_limit = CallLimits.find_reached_call_limit(call_limit_settings, call_started_at, read_guest_speech_activity(), event_loop.time())
            if call_limit is not None:
                return call_limit
            await asyncio.sleep(
                CallLimits.count_seconds_until_a_limit_could_be_reached(
                    call_limit_settings, call_started_at, read_guest_speech_activity(), event_loop.time()
                )
            )

    @staticmethod
    async def _settle_call_limit_enforcement(call_limit_enforcement: asyncio.Task[None]) -> None:
        # Enforcement waits until a limit or the end of the call, so a call that ends first cancels it; awaiting it
        # re-raises a failure to ask for the farewell.
        call_limit_enforcement.cancel()
        try:
            await call_limit_enforcement
        except asyncio.CancelledError:
            # Only the cancellation the relay requested ends here; one aimed at the task holding the call goes on.
            if ManagerConversation._is_current_task_being_cancelled():
                raise

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
        call_end_signals: CallEndSignals,
        read_sent_agent_speech: Callable[[], SentAgentSpeech | None],
    ) -> None:
        # The part already cut off is remembered, so one part is cut off once however many reports follow.
        cut_off_agent_speech_part: AgentSpeechPart | None = None
        guest_audio_allowance: GuestAudioAllowance = GuestAudioPacing.start_allowance(
            realtime_voice_session.conversation_audio_format.guest_audio_sample_rate_hz, asyncio.get_running_loop().time()
        )
        try:
            guest_side_event: GuestSideEvent
            async for guest_side_event in guest_side_events:
                # Once a limit is reached the guest hears the farewell; nothing more reaches a session that is about to
                # close, so nothing is sent to one already closed.
                if call_end_signals.reached_call_limit.done():
                    continue
                match guest_side_event:
                    case GuestSpeechChunk(pcm_audio=pcm_audio):
                        guest_audio_allowance = await ManagerConversation._forward_guest_speech(
                            realtime_voice_session, pcm_audio, guest_audio_allowance
                        )
                    case AgentSpeechCutOff():
                        cut_off_agent_speech_part = await ManagerConversation._cut_off_agent_speech(
                            realtime_voice_session, guest_side_event, read_sent_agent_speech(), cut_off_agent_speech_part
                        )
        finally:
            # The guest hung up or forwarding failed. Closing the session ends the event relay.
            call_end_signals.guest_audio_ended.set()
            await realtime_voice_session.close()

    @staticmethod
    async def _forward_guest_speech(
        realtime_voice_session: RealtimeVoiceSessionBase, pcm_audio: bytes, guest_audio_allowance: GuestAudioAllowance
    ) -> GuestAudioAllowance:
        """Sends a piece of guest speech the pacing admits and returns the allowance left; a piece it does not admit is dropped."""
        guest_audio_sample_rate_hz: int = realtime_voice_session.conversation_audio_format.guest_audio_sample_rate_hz
        refilled_guest_audio_allowance: GuestAudioAllowance = GuestAudioPacing.refill_allowance(
            guest_audio_allowance, guest_audio_sample_rate_hz, asyncio.get_running_loop().time()
        )
        if not GuestAudioPacing.admits_guest_speech(refilled_guest_audio_allowance, len(pcm_audio), guest_audio_sample_rate_hz):
            return refilled_guest_audio_allowance
        await realtime_voice_session.send_guest_audio(pcm_audio)
        return GuestAudioPacing.spend_allowance(refilled_guest_audio_allowance, len(pcm_audio))

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
