from voice_agent_conversation.managers.models.conversation_models import AgentSpeechReceived, SentAgentSpeech


class AgentSpeechPlayback:
    """How much of the agent's current speech has been sent to the guest, which is what a later cut-off is measured against."""

    @staticmethod
    def count_sent_agent_speech(sent_agent_speech: SentAgentSpeech | None, agent_speech_received: AgentSpeechReceived) -> SentAgentSpeech:
        """Adds a piece of speech to the count of the part it belongs to; a piece of a new part starts a new count."""
        if sent_agent_speech is None or sent_agent_speech.agent_speech_part != agent_speech_received.agent_speech_part:
            return SentAgentSpeech(agent_speech_part=agent_speech_received.agent_speech_part, sent_byte_count=len(agent_speech_received.pcm_audio))
        return SentAgentSpeech(
            agent_speech_part=sent_agent_speech.agent_speech_part,
            sent_byte_count=sent_agent_speech.sent_byte_count + len(agent_speech_received.pcm_audio),
        )
