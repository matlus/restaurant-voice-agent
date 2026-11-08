from dataclasses import dataclass
from enum import StrEnum


class SpeechProvider(StrEnum):
    OPENAI = "openai"


class PresentedGender(StrEnum):
    """How a voice presents to listeners. Providers do not label their voices this way; the catalog does."""

    FEMALE = "female"
    MALE = "male"


@dataclass(frozen=True)
class VoiceOption:
    """One voice a guest can talk to, as listed in the voice catalog."""

    voice_key: str
    speech_provider: SpeechProvider
    provider_voice_id: str
    presented_gender: PresentedGender
    description: str


@dataclass(frozen=True)
class ConversationRequest:
    """What a host knows when a guest opens a conversation. Values arrive as received; the manager normalizes them."""

    voice_key: str | None


@dataclass(frozen=True)
class ConversationAudioFormat:
    """Both directions carry mono 16-bit little-endian PCM at these sample rates."""

    guest_audio_sample_rate_hz: int
    agent_audio_sample_rate_hz: int


@dataclass(frozen=True)
class ConversationStarted:
    """The first event of every conversation. Guest audio must be sent in this format from now on."""

    audio_format: ConversationAudioFormat
    voice_option: VoiceOption


@dataclass(frozen=True)
class AgentSpeechChunk:
    """The next piece of the agent's speech, to be played straight after the previous one."""

    pcm_audio: bytes


@dataclass(frozen=True)
class GuestStartedSpeaking:
    """The guest began talking. Any agent speech still queued for playback must stop at once."""


@dataclass(frozen=True)
class AgentTurnFinished:
    """The agent finished, or abandoned, its current reply."""


@dataclass(frozen=True)
class AgentToolCallRequested:
    """The speech model asks to run one of its tools. The answer goes back under the same call_id.

    arguments_json is the model's arguments exactly as it sent them; the tool checks them against its input.
    """

    call_id: str
    tool_name: str
    arguments_json: str


type ConversationEvent = ConversationStarted | AgentSpeechChunk | GuestStartedSpeaking | AgentTurnFinished

type AgentSessionEvent = AgentSpeechChunk | GuestStartedSpeaking | AgentTurnFinished

type VoiceSessionEvent = AgentSessionEvent | AgentToolCallRequested

# A JSON Schema document, as the speech model reads a tool's parameters.
type JsonSchema = dict[str, object]


@dataclass(frozen=True)
class AgentToolDefinition:
    """One tool the speech model may call, described in a provider-neutral way. Each gateway sends it in its provider's form."""

    name: str
    description: str
    parameters_schema: JsonSchema


@dataclass(frozen=True)
class VoiceSessionSettings:
    """How the speech provider must behave for one conversation."""

    provider_voice_id: str
    agent_instructions: str
    agent_tool_definitions: tuple[AgentToolDefinition, ...]
