from collections.abc import Iterable, Mapping
from typing import Final

from voice_agent_conversation import (
    AgentSpeechChunk,
    AgentTurnFinished,
    CallLimit,
    CallLimitReached,
    ConversationStarted,
    GuestFacingConversationEvent,
    GuestStartedSpeaking,
    VoiceOption,
)
from voice_agent_web.resource_models.conversation_resources import ConversationMessage, VoiceResource, VoicesResource


class ComposerConversationMessages:
    """The browser's page tells agent speech from everything else by frame type alone and plays every binary frame as
    PCM at the announced agent sample rate, so nothing but speech may ever be composed as bytes."""

    # What the page shows once the call has ended; the agent has already said goodbye.
    CALL_LIMIT_DETAIL_BY_CALL_LIMIT: Final[Mapping[CallLimit, str]] = {
        CallLimit.MAXIMUM_DURATION: "The call reached its time limit. You're welcome to call again.",
        CallLimit.MAXIMUM_SILENCE: "The call ended because we couldn't hear you. You're welcome to call again.",
    }

    @staticmethod
    def compose_event(guest_facing_conversation_event: GuestFacingConversationEvent) -> ConversationMessage:
        match guest_facing_conversation_event:
            case AgentSpeechChunk(pcm_audio=pcm_audio):
                return pcm_audio
            case ConversationStarted(conversation_audio_format=conversation_audio_format, voice_option=voice_option):
                return {
                    "type": "conversation_started",
                    "guest_audio_sample_rate_hz": conversation_audio_format.guest_audio_sample_rate_hz,
                    "agent_audio_sample_rate_hz": conversation_audio_format.agent_audio_sample_rate_hz,
                    "voice": ComposerConversationMessages.compose_voice(voice_option),
                }
            case GuestStartedSpeaking():
                return {"type": "guest_started_speaking"}
            case AgentTurnFinished():
                return {"type": "agent_turn_finished"}
            case CallLimitReached(call_limit=call_limit):
                return {
                    "type": "call_limit_reached",
                    "call_limit": call_limit.value,
                    "detail": ComposerConversationMessages.CALL_LIMIT_DETAIL_BY_CALL_LIMIT[call_limit],
                }

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
