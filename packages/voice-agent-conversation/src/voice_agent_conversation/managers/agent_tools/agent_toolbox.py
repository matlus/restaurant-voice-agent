from dataclasses import dataclass
from typing import Final, final

import pydantic_core

from voice_agent_conversation.managers.agent_tools.agent_tool_protocol import AgentToolProtocol
from voice_agent_conversation.managers.agent_tools.restaurant_tools.agent_tool_book_table import AgentToolBookTable
from voice_agent_conversation.managers.agent_tools.restaurant_tools.agent_tool_cancel_booking import AgentToolCancelBooking
from voice_agent_conversation.managers.agent_tools.restaurant_tools.agent_tool_change_booking import AgentToolChangeBooking
from voice_agent_conversation.managers.agent_tools.restaurant_tools.agent_tool_check_availability import AgentToolCheckAvailability
from voice_agent_conversation.managers.agent_tools.restaurant_tools.agent_tool_describe_dish import AgentToolDescribeDish
from voice_agent_conversation.managers.agent_tools.restaurant_tools.agent_tool_find_bookings import AgentToolFindBookings
from voice_agent_conversation.managers.agent_tools.restaurant_tools.agent_tool_get_opening_hours import AgentToolGetOpeningHours
from voice_agent_conversation.managers.agent_tools.restaurant_tools.agent_tool_search_menu import AgentToolSearchMenu
from voice_agent_conversation.managers.exceptions.agent_tool_exceptions import (
    AgentToolArgumentsInvalidException,
    AgentToolCallRepairsExhaustedException,
)
from voice_agent_conversation.managers.models.conversation_models import AgentToolCallRequested, AgentToolDefinition
from voice_agent_restaurant import DomainFacade as RestaurantDomainFacade, VoiceAgentRestaurantBusinessBaseException


@final
@dataclass(frozen=True)
class AgentToolRefusal:
    """What the agent is told when the restaurant refuses a request, so it can tell the caller and offer another way."""

    refused: bool
    reason: str


@final
@dataclass(frozen=True)
class AgentToolCallRejection:
    """What the agent is told when its own call was wrong, so it can call again correctly."""

    call_rejected: bool
    problem: str
    instruction: str


@final
class AgentToolbox:
    """The tools one conversation's agent can call, run on its behalf.

    A refusal by the restaurant, such as a full evening or a closed day, comes back as an answer the agent passes on.
    A wrong call by the agent, such as an unknown tool or arguments that do not fit, comes back as a correction it can
    act on, a limited number of times per conversation. Anything else, such as the store being unreachable, ends the call.
    """

    MAXIMUM_CALL_REPAIRS: Final[int] = 3
    CALL_AGAIN_INSTRUCTION: Final[str] = "Call the tool again with arguments that match its parameters, or use another tool."

    def __init__(self, restaurant_domain_facade: RestaurantDomainFacade) -> None:
        agent_tools: list[AgentToolProtocol] = [
            AgentToolSearchMenu(restaurant_domain_facade),
            AgentToolDescribeDish(restaurant_domain_facade),
            AgentToolGetOpeningHours(restaurant_domain_facade),
            AgentToolCheckAvailability(restaurant_domain_facade),
            AgentToolBookTable(restaurant_domain_facade),
            AgentToolFindBookings(restaurant_domain_facade),
            AgentToolChangeBooking(restaurant_domain_facade),
            AgentToolCancelBooking(restaurant_domain_facade),
        ]
        self._agent_tools_by_name: dict[str, AgentToolProtocol] = {agent_tool.name: agent_tool for agent_tool in agent_tools}
        self._call_repair_count: int = 0

    def get_tool_definitions(self) -> tuple[AgentToolDefinition, ...]:
        return tuple(agent_tool.get_tool_definition() for agent_tool in self._agent_tools_by_name.values())

    async def run_tool_call(self, agent_tool_call_requested: AgentToolCallRequested) -> str:
        """Runs the requested tool and returns the JSON the agent reads: the tool's result, a refusal or a correction."""
        agent_tool: AgentToolProtocol | None = self._agent_tools_by_name.get(agent_tool_call_requested.tool_name)
        if agent_tool is None:
            return self._reject_call(
                agent_tool_call_requested.tool_name,
                f"There is no tool named '{agent_tool_call_requested.tool_name}'. The tools are: {', '.join(self._agent_tools_by_name)}.",
            )
        try:
            return await agent_tool.invoke(agent_tool_call_requested.arguments_json)
        except AgentToolArgumentsInvalidException as agent_tool_arguments_invalid_exception:
            return self._reject_call(agent_tool.name, agent_tool_arguments_invalid_exception.message)
        except VoiceAgentRestaurantBusinessBaseException as voice_agent_restaurant_business_exception:
            # Translated, not swallowed: the refusal becomes the answer the agent relays to the caller.
            return pydantic_core.to_json(AgentToolRefusal(refused=True, reason=voice_agent_restaurant_business_exception.message)).decode("utf-8")

    def _reject_call(self, tool_name: str, problem: str) -> str:
        if self._call_repair_count >= self.MAXIMUM_CALL_REPAIRS:
            raise AgentToolCallRepairsExhaustedException(tool_name=tool_name, repair_limit=self.MAXIMUM_CALL_REPAIRS, last_problem=problem)
        self._call_repair_count += 1
        return pydantic_core.to_json(AgentToolCallRejection(call_rejected=True, problem=problem, instruction=self.CALL_AGAIN_INSTRUCTION)).decode(
            "utf-8"
        )
