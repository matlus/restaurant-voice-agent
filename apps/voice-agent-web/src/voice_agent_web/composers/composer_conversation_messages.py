from collections.abc import Iterable

from voice_agent_conversation import AgentSpeechChunk, AgentTurnFinished, ConversationEvent, ConversationStarted, GuestStartedSpeaking, VoiceOption
from voice_agent_web.resource_models.conversation_resources import ConversationMessage, VoiceResource, VoicesResource


class ComposerConversationMessages:
    """The browser's page tells agent speech from everything else by frame type alone and plays every binary frame as
    PCM at the announced agent sample rate, so nothing but speech may ever be composed as bytes."""

    @staticmethod
    def compose_event(conversation_event: ConversationEvent) -> ConversationMessage:
        match conversation_event:
            case AgentSpeechChunk(pcm_audio=pcm_audio):
                return pcm_audio
            case ConversationStarted(audio_format=audio_format, voice_option=voice_option):
                return {
                    "type": "conversation_started",
                    "guest_audio_sample_rate_hz": audio_format.guest_audio_sample_rate_hz,
                    "agent_audio_sample_rate_hz": audio_format.agent_audio_sample_rate_hz,
                    "voice": ComposerConversationMessages.compose_voice(voice_option),
                }
            case GuestStartedSpeaking():
                return {"type": "guest_started_speaking"}
            case AgentTurnFinished():
                return {"type": "agent_turn_finished"}

    @staticmethod
    def compose_voice(voice_option: VoiceOption) -> VoiceResource:
        return {
            "voice_key": voice_option.voice_key,
            "presented_gender": voice_option.presented_gender.value,
            "description": voice_option.description,
        }

    @staticmethod
    def compose_voices(voice_options: Iterable[VoiceOption]) -> VoicesResource:
        return {"voices": [ComposerConversationMessages.compose_voice(voice_option) for voice_option in voice_options]}
