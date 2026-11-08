import re
from typing import Final

from voice_agent_conversation.managers.exceptions.conversation_exceptions import ConversationRequestValidationException, LogEventConversation
from voice_agent_conversation.managers.models.conversation_models import ConversationRequest


class ValidatorConversationRequests:
    """Normalizes and validates conversation requests before anything else happens. Reports every problem at once."""

    MAXIMUM_VOICE_KEY_LENGTH: Final[int] = 64
    VOICE_KEY_PATTERN: Final[re.Pattern[str]] = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")

    @classmethod
    def validate_conversation_request(cls, conversation_request: ConversationRequest) -> str:
        validation_problems: list[str] = []
        voice_key: str | None = cls._normalize_voice_key(conversation_request.voice_key)
        if voice_key is None:
            validation_problems.append("A voice is required.")
        elif len(voice_key) > cls.MAXIMUM_VOICE_KEY_LENGTH:
            validation_problems.append(
                f"The voice key '{voice_key[: cls.MAXIMUM_VOICE_KEY_LENGTH]}...' must be at most {cls.MAXIMUM_VOICE_KEY_LENGTH} characters."
            )
        elif cls.VOICE_KEY_PATTERN.fullmatch(voice_key) is None:
            validation_problems.append(f"The voice key '{voice_key}' may contain only letters, digits and single hyphens between them.")
        if voice_key is None or validation_problems:
            raise ConversationRequestValidationException(validation_problems, LogEventConversation.CONVERSATION_START)
        return voice_key

    @staticmethod
    def _normalize_voice_key(requested_voice_key: str | None) -> str | None:
        """The voice key trimmed and lower-cased, or None when no voice was asked for: missing, or nothing but whitespace."""
        if requested_voice_key is None or requested_voice_key.isspace() or not requested_voice_key:
            return None
        return requested_voice_key.strip().lower()
