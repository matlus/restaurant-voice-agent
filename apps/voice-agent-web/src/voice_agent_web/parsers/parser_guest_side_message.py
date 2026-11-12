from pydantic import ValidationError
from starlette.types import Message

from voice_agent_conversation import AgentSpeechCutOff, GuestSideEvent, GuestSpeechChunk
from voice_agent_web.resource_models.guest_side_resources import AgentSpeechCutOffMessage


class ParserGuestSideMessage:
    """Turns one WebSocket message from the browser's page into what the guest's side tells the domain.

    A binary frame is guest speech. A text frame must be the page's agent speech cut-off report, checked against its wire
    model. Any other text frame, or a report that breaks the model, carries nothing the call can use and is passed over,
    as text frames always have been, so a page that sends something new cannot end a call.
    """

    @staticmethod
    def parse(websocket_message: Message) -> GuestSideEvent | None:
        guest_audio: bytes | None = websocket_message.get("bytes")
        if guest_audio:
            return GuestSpeechChunk(pcm_audio=guest_audio)
        message_text: str | None = websocket_message.get("text")
        if message_text is None:
            return None
        try:
            agent_speech_cut_off_message: AgentSpeechCutOffMessage = AgentSpeechCutOffMessage.model_validate_json(message_text)
        except ValidationError:
            return None
        return AgentSpeechCutOff(unplayed_milliseconds=agent_speech_cut_off_message.unplayed_milliseconds)
