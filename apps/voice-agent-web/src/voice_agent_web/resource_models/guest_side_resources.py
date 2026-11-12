from typing import Literal

from pydantic import BaseModel, ConfigDict, NonNegativeInt


class AgentSpeechCutOffMessage(BaseModel):
    """The page's report that it dropped agent speech it had not played, as it arrives on the wire."""

    model_config = ConfigDict(strict=True, frozen=True)

    type: Literal["agent_speech_cut_off"]
    unplayed_milliseconds: NonNegativeInt
