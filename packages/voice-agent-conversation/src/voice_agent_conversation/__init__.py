"""Real-time voice conversations with the restaurant's agent. Import everything from this package's root."""

from voice_agent_conversation.domain_facade import DomainFacade
from voice_agent_conversation.managers.exceptions.agent_tool_exceptions import AgentToolCallRepairsExhaustedException, LogEventAgentTool
from voice_agent_conversation.managers.exceptions.configuration_exceptions import ConfigurationSettingException, LogEventConfiguration
from voice_agent_conversation.managers.exceptions.conversation_exceptions import (
    ConversationRequestValidationException,
    LogEventConversation,
    VoiceCatalogInvalidException,
    VoiceNotOfferedException,
)
from voice_agent_conversation.managers.exceptions.realtime_voice_exceptions import (
    LogEventRealtimeVoice,
    RealtimeVoiceProviderAccessDeniedException,
    RealtimeVoiceProviderErrorException,
    RealtimeVoiceProviderUnavailableException,
)
from voice_agent_conversation.managers.exceptions.voice_agent_conversation_exceptions import (
    ExceptionAction,
    LogEventBase,
    Severity,
    VoiceAgentConversationBaseException,
    VoiceAgentConversationBusinessBaseException,
    VoiceAgentConversationTechnicalBaseException,
)
from voice_agent_conversation.managers.models.conversation_models import (
    AgentSpeechChunk,
    AgentTurnFinished,
    ConversationAudioFormat,
    ConversationEvent,
    ConversationRequest,
    ConversationStarted,
    GuestStartedSpeaking,
    PresentedGender,
    SpeechProvider,
    VoiceOption,
)

__all__ = [
    "AgentSpeechChunk",
    "AgentToolCallRepairsExhaustedException",
    "AgentTurnFinished",
    "ConfigurationSettingException",
    "ConversationAudioFormat",
    "ConversationEvent",
    "ConversationRequest",
    "ConversationRequestValidationException",
    "ConversationStarted",
    "DomainFacade",
    "ExceptionAction",
    "GuestStartedSpeaking",
    "LogEventAgentTool",
    "LogEventBase",
    "LogEventConfiguration",
    "LogEventConversation",
    "LogEventRealtimeVoice",
    "PresentedGender",
    "RealtimeVoiceProviderAccessDeniedException",
    "RealtimeVoiceProviderErrorException",
    "RealtimeVoiceProviderUnavailableException",
    "Severity",
    "SpeechProvider",
    "VoiceAgentConversationBaseException",
    "VoiceAgentConversationBusinessBaseException",
    "VoiceAgentConversationTechnicalBaseException",
    "VoiceCatalogInvalidException",
    "VoiceNotOfferedException",
    "VoiceOption",
]
