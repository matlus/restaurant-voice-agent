import asyncio
from collections.abc import AsyncIterable, Callable
from typing import final

from voice_agent_conversation.managers.gateways.realtime_voice_gateway_base import RealtimeVoiceSessionBase
from voice_agent_conversation.managers.models.conversation_models import (
    AgentSpeechCutOff,
    AgentSpeechPart,
    CallEndSignals,
    GuestAudioAllowance,
    GuestSideEvent,
    GuestSpeechChunk,
    SentAgentSpeech,
)
from voice_agent_conversation.managers.processors.rules.agent_speech_cut_offs import AgentSpeechCutOffs
from voice_agent_conversation.managers.processors.rules.guest_audio_pacing import GuestAudioPacing


@final
class ProcessorGuestSideForwarding:
    """Passes what the guest's side of one call sends on to the speech provider: guest speech the pacing admits, and
    cut-off reports as a cut in the agent's reply where the guest stopped hearing it. When the guest's side ends, it says
    so and closes the session, which ends the event relay."""

    def __init__(
        self,
        realtime_voice_session: RealtimeVoiceSessionBase,
        call_end_signals: CallEndSignals,
        read_sent_agent_speech: Callable[[], SentAgentSpeech | None],
    ) -> None:
        self._realtime_voice_session: RealtimeVoiceSessionBase = realtime_voice_session
        self._call_end_signals: CallEndSignals = call_end_signals
        self._read_sent_agent_speech: Callable[[], SentAgentSpeech | None] = read_sent_agent_speech

    async def forward_guest_side_events(self, guest_side_events: AsyncIterable[GuestSideEvent]) -> None:
        # The part already cut off is remembered, so one part is cut off once however many reports follow.
        cut_off_agent_speech_part: AgentSpeechPart | None = None
        guest_audio_allowance: GuestAudioAllowance = GuestAudioPacing.start_allowance(
            self._realtime_voice_session.conversation_audio_format.guest_audio_sample_rate_hz, asyncio.get_running_loop().time()
        )
        try:
            guest_side_event: GuestSideEvent
            async for guest_side_event in guest_side_events:
                # Once a limit is reached the guest hears the farewell; nothing more reaches a session that is about to
                # close, so nothing is sent to one already closed.
                if self._call_end_signals.reached_call_limit.done():
                    continue
                match guest_side_event:
                    case GuestSpeechChunk(pcm_audio=pcm_audio):
                        guest_audio_allowance = await self._forward_guest_speech(pcm_audio, guest_audio_allowance)
                    case AgentSpeechCutOff():
                        cut_off_agent_speech_part = await self._cut_off_agent_speech(guest_side_event, cut_off_agent_speech_part)
        finally:
            # The guest hung up or forwarding failed. Closing the session ends the event relay.
            self._call_end_signals.guest_audio_ended.set()
            await self._realtime_voice_session.close()

    async def _forward_guest_speech(self, pcm_audio: bytes, guest_audio_allowance: GuestAudioAllowance) -> GuestAudioAllowance:
        # A dropped piece is not queued for later: speech that arrives too fast is lost, so a runaway sender costs nothing.
        guest_audio_sample_rate_hz: int = self._realtime_voice_session.conversation_audio_format.guest_audio_sample_rate_hz
        refilled_guest_audio_allowance: GuestAudioAllowance = GuestAudioPacing.refill_allowance(
            guest_audio_allowance, guest_audio_sample_rate_hz, asyncio.get_running_loop().time()
        )
        if not GuestAudioPacing.admits_guest_speech(refilled_guest_audio_allowance, len(pcm_audio), guest_audio_sample_rate_hz):
            return refilled_guest_audio_allowance
        await self._realtime_voice_session.send_guest_audio(pcm_audio)
        return GuestAudioPacing.spend_allowance(refilled_guest_audio_allowance, len(pcm_audio))

    async def _cut_off_agent_speech(
        self, agent_speech_cut_off: AgentSpeechCutOff, cut_off_agent_speech_part: AgentSpeechPart | None
    ) -> AgentSpeechPart | None:
        """Returns the part cut off so far, which the caller hands back with the next report: a report that removes nothing
        the guest did not hear, or names a part already cut off, changes nothing."""
        sent_agent_speech: SentAgentSpeech | None = self._read_sent_agent_speech()
        if sent_agent_speech is None or not AgentSpeechCutOffs.drops_unheard_speech(
            sent_agent_speech, agent_speech_cut_off, cut_off_agent_speech_part
        ):
            return cut_off_agent_speech_part
        heard_milliseconds: int = AgentSpeechCutOffs.to_heard_milliseconds(
            sent_agent_speech,
            agent_speech_cut_off.unplayed_milliseconds,
            self._realtime_voice_session.conversation_audio_format.agent_audio_sample_rate_hz,
        )
        await self._realtime_voice_session.cut_off_agent_speech(sent_agent_speech.agent_speech_part, heard_milliseconds)
        return sent_agent_speech.agent_speech_part
