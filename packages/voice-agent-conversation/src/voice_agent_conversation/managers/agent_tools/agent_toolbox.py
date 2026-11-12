from dataclasses import dataclass
from typing import Final, final

import pydantic_core

from voice_agent_conversation.managers.agent_tools.agent_tool_protocol import AgentToolProtocol
from voice_agent_conversation.managers.agent_tools.restaurant_tools.agent_tool_book_table import AgentToolBookTable
from voice_agent_conversation.managers.agent_tools.restaurant_tools.agent_tool_cancel_booking import AgentToolCancelBooking
from voice_agent_conversation.managers.agent_tools.restaurant_tools.agent_tool_cancel_booking_by_details import AgentToolCancelBookingByDetails
from voice_agent_conversation.managers.agent_tools.restaurant_tools.agent_tool_change_booking import AgentToolChangeBooking
from voice_agent_conversation.managers.agent_tools.restaurant_tools.agent_tool_change_booking_by_details import AgentToolChangeBookingByDetails
from voice_agent_conversation.managers.agent_tools.restaurant_tools.agent_tool_check_availability import AgentToolCheckAvailability
from voice_agent_conversation.managers.agent_tools.restaurant_tools.agent_tool_describe_dish import AgentToolDescribeDish
from voice_agent_conversation.managers.agent_tools.restaurant_tools.agent_tool_find_bookings import AgentToolFindBookings
from voice_agent_conversation.managers.agent_tools.restaurant_tools.agent_tool_get_opening_hours import AgentToolGetOpeningHours
from voice_agent_conversation.managers.agent_tools.restaurant_tools.agent_tool_search_menu import AgentToolSearchMenu
from voice_agent_conversation.managers.exceptions.agent_tool_exceptions import (
    AgentToolArgumentsInvalidException,
    AgentToolCallRepairsExhaustedException,
)
from voice_agent_conversation.managers.models.conversation_models import AgentToolCallOutcome, AgentToolCallRequested, AgentToolDefinition
from voice_agent_restaurant import (
    DishLookupValidationException,
    DomainFacade as RestaurantDomainFacade,
    MenuSearchValidationException,
    ReservationRequestValidationException,
    VoiceAgentRestaurantBusinessBaseException,
)


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
@dataclass(frozen=True)
class AgentToolCallAnswer:
    """The JSON the agent reads for one tool call, how the call was answered, and how many of its calls in a row have now
    been wrong."""

    tool_output_json: str
    agent_tool_call_outcome: AgentToolCallOutcome
    consecutive_call_repair_count: int


@final
class AgentToolbox:
    """The tools the agent can call, run on its behalf.

    A refusal by the restaurant, such as a full evening, a closed day or a party too large to book by phone, comes back
    as an answer the agent passes on. A wrong call by the agent, such as an unknown tool, arguments that do not fit or a
    value the restaurant cannot read (a time given as "half past six"), comes back as a correction the agent acts on
    without troubling the caller. Only a run of wrong calls with nothing accepted between them ends the call, because a
    misheard detail now and then is ordinary. The caller carries that run from one call to the next; the toolbox keeps
    no history, so one toolbox serves every conversation. Anything else, such as the store being unreachable, ends the call.
    """

    MAXIMUM_CALL_REPAIRS: Final[int] = 3
    CALL_AGAIN_INSTRUCTION: Final[str] = (
        "Fix the call yourself and call the tool again, or use another tool. Don't mention this problem, formats or tools to "
        "the caller; ask them only for a detail you don't have, in plain words."
    )

    def __init__(self, restaurant_domain_facade: RestaurantDomainFacade) -> None:
        agent_tools: list[AgentToolProtocol] = [
            AgentToolSearchMenu(restaurant_domain_facade),
            AgentToolDescribeDish(restaurant_domain_facade),
            AgentToolGetOpeningHours(restaurant_domain_facade),
            AgentToolCheckAvailability(restaurant_domain_facade),
            AgentToolBookTable(restaurant_domain_facade),
            AgentToolFindBookings(restaurant_domain_facade),
            AgentToolChangeBooking(restaurant_domain_facade),
            AgentToolChangeBookingByDetails(restaurant_domain_facade),
            AgentToolCancelBooking(restaurant_domain_facade),
            AgentToolCancelBookingByDetails(restaurant_domain_facade),
        ]
        self._agent_tools_by_name: dict[str, AgentToolProtocol] = {agent_tool.name: agent_tool for agent_tool in agent_tools}

    def get_tool_definitions(self) -> tuple[AgentToolDefinition, ...]:
        return tuple(agent_tool.get_tool_definition() for agent_tool in self._agent_tools_by_name.values())

    async def run_tool_call(self, agent_tool_call_requested: AgentToolCallRequested, consecutive_call_repair_count: int) -> AgentToolCallAnswer:
        """Raises AgentToolCallRepairsExhaustedException, which ends the call, once too many wrong calls have come in a row."""
        agent_tool: AgentToolProtocol | None = self._agent_tools_by_name.get(agent_tool_call_requested.tool_name)
        if agent_tool is None:
            return self._reject_call(
                agent_tool_call_requested.tool_name, self._describe_unknown_tool(agent_tool_call_requested.tool_name), consecutive_call_repair_count
            )
        try:
            tool_output_json: str = await agent_tool.invoke(agent_tool_call_requested.arguments_json)
        except AgentToolArgumentsInvalidException as agent_tool_arguments_invalid_exception:
            return self._reject_call(agent_tool.name, agent_tool_arguments_invalid_exception.message, consecutive_call_repair_count)
        except (ReservationRequestValidationException, MenuSearchValidationException, DishLookupValidationException) as request_validation_exception:
            # The restaurant could not read what the agent sent. That is the agent's call to fix, not a refusal for the caller.
            return self._reject_call(agent_tool.name, request_validation_exception.message, consecutive_call_repair_count)
        except VoiceAgentRestaurantBusinessBaseException as voice_agent_restaurant_business_exception:
            # Translated, not swallowed: the refusal becomes the answer the agent relays to the caller.
            return self._relay_refusal(voice_agent_restaurant_business_exception)
        return self._accept_call(tool_output_json)

    def _describe_unknown_tool(self, tool_name: str) -> str:
        return f"There is no tool named '{tool_name}'. The tools are: {', '.join(self._agent_tools_by_name)}."

    def _reject_call(self, tool_name: str, problem: str, consecutive_call_repair_count: int) -> AgentToolCallAnswer:
        if consecutive_call_repair_count >= self.MAXIMUM_CALL_REPAIRS:
            raise AgentToolCallRepairsExhaustedException(tool_name=tool_name, repair_limit=self.MAXIMUM_CALL_REPAIRS)
        agent_tool_call_rejection: AgentToolCallRejection = AgentToolCallRejection(
            call_rejected=True, problem=problem, instruction=self.CALL_AGAIN_INSTRUCTION
        )
        return AgentToolCallAnswer(
            tool_output_json=pydantic_core.to_json(agent_tool_call_rejection).decode("utf-8"),
            agent_tool_call_outcome=AgentToolCallOutcome.CORRECTED,
            consecutive_call_repair_count=consecutive_call_repair_count + 1,
        )

    @staticmethod
    def _relay_refusal(voice_agent_restaurant_business_exception: VoiceAgentRestaurantBusinessBaseException) -> AgentToolCallAnswer:
        agent_tool_refusal: AgentToolRefusal = AgentToolRefusal(refused=True, reason=voice_agent_restaurant_business_exception.message)
        return AgentToolCallAnswer(
            tool_output_json=pydantic_core.to_json(agent_tool_refusal).decode("utf-8"),
            agent_tool_call_outcome=AgentToolCallOutcome.REFUSED,
            consecutive_call_repair_count=0,
        )

    @staticmethod
    def _accept_call(tool_output_json: str) -> AgentToolCallAnswer:
        return AgentToolCallAnswer(
            tool_output_json=tool_output_json, agent_tool_call_outcome=AgentToolCallOutcome.ANSWERED, consecutive_call_repair_count=0
        )
