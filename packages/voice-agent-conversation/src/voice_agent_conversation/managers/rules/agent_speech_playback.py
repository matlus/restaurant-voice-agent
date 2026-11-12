from typing import Final

from voice_agent_conversation.managers.models.conversation_models import AgentSpeechCutOff, AgentSpeechPart, AgentSpeechReceived, SentAgentSpeech


class AgentSpeechPlayback:
    """How much of the agent's speech the guest has heard. The provider sends speech faster than it is played, so the host
    reports how much it dropped unplayed, and what was heard is what was sent less what was dropped."""

    # Mono 16-bit PCM.
    BYTES_PER_SAMPLE: Final[int] = 2
    MILLISECONDS_PER_SECOND: Final[int] = 1_000

    @staticmethod
    def count_sent_agent_speech(sent_agent_speech: SentAgentSpeech | None, agent_speech_received: AgentSpeechReceived) -> SentAgentSpeech:
        """Adds a piece of speech to the count of the part it belongs to; a piece of a new part starts a new count."""
        if sent_agent_speech is None or sent_agent_speech.agent_speech_part != agent_speech_received.agent_speech_part:
            return SentAgentSpeech(agent_speech_part=agent_speech_received.agent_speech_part, sent_byte_count=len(agent_speech_received.pcm_audio))
        return SentAgentSpeech(
            agent_speech_part=sent_agent_speech.agent_speech_part,
            sent_byte_count=sent_agent_speech.sent_byte_count + len(agent_speech_received.pcm_audio),
        )

    @staticmethod
    def drops_unheard_speech(
        sent_agent_speech: SentAgentSpeech, agent_speech_cut_off: AgentSpeechCutOff, cut_off_agent_speech_part: AgentSpeechPart | None
    ) -> bool:
        """Whether a cut-off report removes speech the guest did not hear: something went unplayed, and that part has not
        already been cut off."""
        return agent_speech_cut_off.unplayed_milliseconds > 0 and sent_agent_speech.agent_speech_part != cut_off_agent_speech_part

    @classmethod
    def to_heard_milliseconds(cls, sent_agent_speech: SentAgentSpeech, unplayed_milliseconds: int, agent_audio_sample_rate_hz: int) -> int:
        """How far into the part the guest heard. A host that dropped more than the part held heard none of it."""
        sent_milliseconds: int = (
            sent_agent_speech.sent_byte_count * cls.MILLISECONDS_PER_SECOND // (cls.BYTES_PER_SAMPLE * agent_audio_sample_rate_hz)
        )
        return max(0, sent_milliseconds - unplayed_milliseconds)
