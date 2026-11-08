from typing import Literal, TypedDict


class VoiceResource(TypedDict):
    voice_key: str
    presented_gender: str
    description: str


class VoicesResource(TypedDict):
    voices: list[VoiceResource]


class ConversationStartedMessage(TypedDict):
    type: Literal["conversation_started"]
    guest_audio_sample_rate_hz: int
    agent_audio_sample_rate_hz: int
    voice: VoiceResource


class GuestStartedSpeakingMessage(TypedDict):
    type: Literal["guest_started_speaking"]


class AgentTurnFinishedMessage(TypedDict):
    type: Literal["agent_turn_finished"]


class ConversationErrorMessage(TypedDict):
    """The last text frame of a failed conversation, sent just before the socket closes."""

    type: Literal["error"]
    title: str
    detail: str


type JsonMessage = ConversationStartedMessage | GuestStartedSpeakingMessage | AgentTurnFinishedMessage

# Speech goes to the browser as a binary frame of PCM; everything else as a JSON text frame.
type ConversationMessage = bytes | JsonMessage
