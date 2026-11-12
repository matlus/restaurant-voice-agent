import asyncio
from collections.abc import Awaitable, Callable
from typing import final

from voice_agent_conversation.managers.configuration_providers.settings_models.call_limit_settings import CallLimitSettings
from voice_agent_conversation.managers.gateways.realtime_voice_gateway_base import RealtimeVoiceSessionBase
from voice_agent_conversation.managers.models.conversation_models import CallEndSignals, CallLimit, GuestSpeechActivity
from voice_agent_conversation.managers.processors.rules.call_limits import CallLimits


@final
class ProcessorCallLimitEnforcement:
    """Ends one call once it runs too long or the guest goes quiet for too long: asks for the farewell and reports the
    limit. A farewell that never finishes would hold the paid session open, so the session is closed after a grace period
    and the call still ends."""

    def __init__(
        self,
        realtime_voice_session: RealtimeVoiceSessionBase,
        call_limit_settings: CallLimitSettings,
        call_end_signals: CallEndSignals,
        read_guest_speech_activity: Callable[[], GuestSpeechActivity],
        request_farewell: Callable[[CallLimit], Awaitable[None]],
    ) -> None:
        self._realtime_voice_session: RealtimeVoiceSessionBase = realtime_voice_session
        self._call_limit_settings: CallLimitSettings = call_limit_settings
        self._call_end_signals: CallEndSignals = call_end_signals
        self._read_guest_speech_activity: Callable[[], GuestSpeechActivity] = read_guest_speech_activity
        self._request_farewell: Callable[[CallLimit], Awaitable[None]] = request_farewell

    async def enforce_call_limits(self) -> None:
        call_limit: CallLimit = await self._wait_for_call_limit()
        # A guest who hung up meanwhile hears no farewell; the call is already ending.
        if self._call_end_signals.guest_audio_ended.is_set():
            return
        await self._request_farewell(call_limit)
        self._call_end_signals.reached_call_limit.set_result(call_limit)
        await self._close_session_after_farewell_grace()

    async def _wait_for_call_limit(self) -> CallLimit:
        event_loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        call_started_at: float = event_loop.time()
        # The wait is recomputed after every sleep: the guest may have spoken meanwhile, which moves the silence limit.
        call_limit: CallLimit | None
        while True:
            call_limit = CallLimits.find_reached_call_limit(
                self._call_limit_settings, call_started_at, self._read_guest_speech_activity(), event_loop.time()
            )
            if call_limit is not None:
                return call_limit
            await asyncio.sleep(
                CallLimits.count_seconds_until_a_limit_could_be_reached(
                    self._call_limit_settings, call_started_at, self._read_guest_speech_activity(), event_loop.time()
                )
            )

    async def _close_session_after_farewell_grace(self) -> None:
        await asyncio.sleep(CallLimits.FAREWELL_GRACE_SECONDS)
        # Told first, so the relay sends nothing to the session being closed under it.
        self._call_end_signals.farewell_grace_ran_out.set()
        await self._realtime_voice_session.close()
