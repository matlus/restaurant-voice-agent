import json
from typing import Final, cast

from starlette.types import Message

from voice_agent_conversation import AgentSpeechCutOff, GuestSideEvent, GuestSpeechChunk


class ParserGuestSideMessage:
    """Turns one WebSocket message from the browser's page into what the guest's side tells the domain.

    A binary frame is guest speech. A text frame is the page's report that it cut agent speech off, giving how much it
    dropped unplayed; the domain decides what that means. Any other text frame carries nothing the call needs and is passed
    over, as it always has been, so a page that sends something new cannot end a call.
    """

    AGENT_SPEECH_CUT_OFF_MESSAGE_TYPE: Final[str] = "agent_speech_cut_off"
    UNPLAYED_MILLISECONDS_FIELD_NAME: Final[str] = "unplayed_milliseconds"

    @classmethod
    def parse(cls, websocket_message: Message) -> GuestSideEvent | None:
        guest_audio: bytes | None = websocket_message.get("bytes")
        if guest_audio:
            return GuestSpeechChunk(pcm_audio=guest_audio)
        message_text: str | None = websocket_message.get("text")
        if message_text is None:
            return None
        return cls._parse_agent_speech_cut_off(message_text)

    @classmethod
    def _parse_agent_speech_cut_off(cls, message_text: str) -> AgentSpeechCutOff | None:
        try:
            decoded_message: object = json.loads(message_text)
        except json.JSONDecodeError:
            return None
        if not isinstance(decoded_message, dict):
            return None
        message_field_by_name: dict[str, object] = cast(dict[str, object], decoded_message)
        unplayed_milliseconds: object = message_field_by_name.get(cls.UNPLAYED_MILLISECONDS_FIELD_NAME)
        # JSON true is a Python bool, which is an int; it is not a duration.
        if (
            message_field_by_name.get("type") != cls.AGENT_SPEECH_CUT_OFF_MESSAGE_TYPE
            or not isinstance(unplayed_milliseconds, int)
            or isinstance(unplayed_milliseconds, bool)
        ):
            return None
        return AgentSpeechCutOff(unplayed_milliseconds=unplayed_milliseconds)
