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

    conversation_audio_format: ConversationAudioFormat
    voice_option: VoiceOption


@dataclass(frozen=True)
class AgentSpeechChunk:
    """The next piece of the agent's speech, to be played straight after the previous one."""

    pcm_audio: bytes


@dataclass(frozen=True)
class GuestStartedSpeaking:
    """The guest began talking. Any agent speech still queued for playback must stop at once."""


@dataclass(frozen=True)
class GuestStoppedSpeaking:
    """The guest stopped talking. The provider answers by itself once it judges the guest's turn over."""


@dataclass(frozen=True)
class SpeechProviderErrorTolerated:
    """The speech provider reported an error that leaves the conversation running, such as refusing a reply request
    because a reply is already under way. The host logs it; the guest is not told."""

    error_type: str
    error_code: str | None
    error_message: str


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


@dataclass(frozen=True)
class GuestSpeechChunk:
    """The next piece of the guest's speech, in the format ConversationStarted gave."""

    pcm_audio: bytes


@dataclass(frozen=True)
class AgentSpeechCutOff:
    """The host dropped agent speech it had received but not yet played, because the guest started talking.

    unplayed_milliseconds is how much it dropped. The provider sends speech faster than it is played, so only the host
    knows where the guest stopped hearing it; the agent is told, so it does not believe the guest heard the rest.
    """

    unplayed_milliseconds: int


# What the guest's side of a call sends the domain: speech, and word that agent speech was cut off unheard.
type GuestSideEvent = GuestSpeechChunk | AgentSpeechCutOff


@dataclass(frozen=True)
class AgentSpeechPart:
    """Which part of which agent reply a piece of speech belongs to, as the speech provider identifies it, so speech the
    guest did not hear can be cut off later."""

    reply_item_id: str
    content_index: int


@dataclass(frozen=True)
class AgentSpeechReceived:
    """A piece of the agent's speech as the session receives it, with the part it belongs to."""

    pcm_audio: bytes
    agent_speech_part: AgentSpeechPart


@dataclass(frozen=True)
class SentAgentSpeech:
    """How much of the agent's latest speech part has been passed on to the host."""

    agent_speech_part: AgentSpeechPart
    sent_byte_count: int


# What the guest's side of a call is sent: the page plays or acts on every one of these.
type GuestFacingConversationEvent = ConversationStarted | AgentSpeechChunk | GuestStartedSpeaking | AgentTurnFinished

type ConversationEvent = GuestFacingConversationEvent | SpeechProviderErrorTolerated

type AgentSessionEvent = AgentSpeechChunk | GuestStartedSpeaking | AgentTurnFinished | SpeechProviderErrorTolerated

type VoiceSessionEvent = (
    AgentSpeechReceived | GuestStartedSpeaking | GuestStoppedSpeaking | AgentTurnFinished | AgentToolCallRequested | SpeechProviderErrorTolerated
)

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
