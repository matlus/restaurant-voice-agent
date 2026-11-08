from collections.abc import AsyncGenerator, AsyncIterable
from types import TracebackType
from typing import Self

from voice_agent_conversation.managers.manager_conversation import ManagerConversation
from voice_agent_conversation.managers.models.conversation_models import ConversationEvent, ConversationRequest, VoiceOption
from voice_agent_conversation.managers.service_locators.service_locator_base import ServiceLocatorBase
from voice_agent_conversation.managers.service_locators.service_locator_production import ServiceLocatorProduction


class DomainFacade:
    """The single public entry point to voice conversations with the restaurant's agent.

    Business refusals raise VoiceAgentConversationBusinessBaseException descendants whose messages can be
    shown to a guest. Provider, configuration and restaurant store trouble raise technical exceptions that
    must not be. Construct one per process and close it when the host stops.
    """

    def __init__(self, service_locator: ServiceLocatorBase | None = None) -> None:
        if service_locator is None:
            service_locator = ServiceLocatorProduction()
        self._manager_conversation: ManagerConversation = ManagerConversation(service_locator)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None) -> None:
        await self.close()

    async def close(self) -> None:
        await self._manager_conversation.close()

    async def get_voice_options(self) -> list[VoiceOption]:
        """Every voice a guest can choose, in catalog order."""
        return await self._manager_conversation.get_voice_options()

    def converse(self, conversation_request: ConversationRequest, guest_audio: AsyncIterable[bytes]) -> AsyncGenerator[ConversationEvent]:
        """Holds one voice conversation, yielding ConversationStarted first and then what happens until the guest audio ends.

        Guest audio is mono 16-bit PCM at the rate ConversationStarted gives. The agent greets the guest first.
        Close the returned iterator (contextlib.aclosing) if you stop reading before it ends.
        """
        return self._manager_conversation.converse(conversation_request, guest_audio)
