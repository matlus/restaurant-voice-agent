from abc import ABC, abstractmethod

import pydantic_core
from pydantic import BaseModel, ValidationError

from voice_agent_conversation.managers.exceptions.agent_tool_exceptions import AgentToolArgumentsInvalidException
from voice_agent_conversation.managers.models.conversation_models import AgentToolDefinition, JsonSchema


class AgentToolBase[TToolInput: BaseModel, TToolOutput](ABC):
    """One thing the voice agent can do during a call. A tool describes itself to the speech model and does the work when asked.

    A concrete tool names itself, describes when to use it, declares its input as a Pydantic model and implements run().
    The base builds the parameter schema from the input model, checks the model's arguments against it and turns the
    result into the JSON the model reads.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """The name the speech model calls the tool by."""

    @property
    @abstractmethod
    def description(self) -> str:
        """What the tool does and when to use it, written for the speech model."""

    @property
    @abstractmethod
    def input_model(self) -> type[TToolInput]: ...

    @abstractmethod
    async def run(self, tool_input: TToolInput) -> TToolOutput:
        """Does the work. The result is made of dataclasses, lists and plain values the model can read as JSON."""

    def get_tool_definition(self) -> AgentToolDefinition:
        parameters_schema: JsonSchema = self.input_model.model_json_schema()
        return AgentToolDefinition(name=self.name, description=self.description, parameters_schema=parameters_schema)

    async def invoke(self, arguments_json: str) -> str:
        """Runs the tool for the speech model's arguments, exactly as it sent them, and returns the result as JSON."""
        try:
            tool_input: TToolInput = self.input_model.model_validate_json(arguments_json)
        except ValidationError as validation_error:
            raise AgentToolArgumentsInvalidException(self.name, str(validation_error)) from validation_error
        tool_output: TToolOutput = await self.run(tool_input)
        return pydantic_core.to_json(tool_output).decode("utf-8")
