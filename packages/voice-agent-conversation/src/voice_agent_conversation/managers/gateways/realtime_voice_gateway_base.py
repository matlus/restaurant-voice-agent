from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from types import TracebackType
from typing import Self

from voice_agent_conversation.managers.models.conversation_models import ConversationAudioFormat, VoiceSessionEvent, VoiceSessionSettings


class RealtimeVoiceSessionBase(ABC):
    """One live speech-to-speech conversation with a provider. Owns its connection until closed."""

    @property
    @abstractmethod
    def audio_format(self) -> ConversationAudioFormat: ...

    @abstractmethod
    async def send_guest_audio(self, pcm_audio: bytes) -> None:
        """Passes on the next piece of the guest's speech. The provider detects turns itself."""

    @abstractmethod
    async def request_agent_response(self) -> None:
        """Asks the agent to speak now without waiting for the guest, as it does to greet them."""

    @abstractmethod
    def receive_events(self) -> AsyncIterator[VoiceSessionEvent]:
        """Yields what happens in the conversation until the session is closed."""

    @abstractmethod
    async def close(self) -> None:
        """Ends the conversation. Safe to call more than once; ends any receive_events iteration."""

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None) -> None:
        await self.close()


class RealtimeVoiceGatewayBase(ABC):
    """Opens speech-to-speech conversations with one provider. Long-lived; owns the provider client."""

    @abstractmethod
    async def open_session(self, voice_session_settings: VoiceSessionSettings) -> RealtimeVoiceSessionBase:
        """Connects and configures a conversation, returning it once the provider has accepted the settings. The caller owns and closes it."""

    @abstractmethod
    async def close(self) -> None:
        """Releases the provider client. Safe to call more than once."""

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None) -> None:
        await self.close()
