from collections.abc import Mapping
from typing import Final

from voice_agent_conversation import ConversationRequest


class ParserConversationRequest:
    """Turns the WebSocket query string into a ConversationRequest. Values pass through verbatim; the domain normalizes and validates."""

    VOICE_QUERY_PARAMETER_NAME: Final[str] = "voice"

    @classmethod
    def parse(cls, query_parameters: Mapping[str, str]) -> ConversationRequest:
        return ConversationRequest(voice_key=query_parameters.get(cls.VOICE_QUERY_PARAMETER_NAME))
