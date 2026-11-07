# HTTP and WebSocket pipeline tests: the real host and the real conversation domain, whose speech gateway talks to a
# scripted Realtime service on this machine. They prove the endpoints exist, speak the browser's wire shape and reach
# the exception translation middleware. What the domain decides is proven by its acceptance tests, and the
# translation table by the translator's class tests.

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import pytest
from conversation_acceptance_support.realtime_voice_service_scripted import SCRIPTED_GREETING_AUDIO, RealtimeVoiceServiceScripted
from conversation_acceptance_support.service_locator_testing import create_domain_facade
from fastapi.testclient import TestClient
from httpx2 import Response
from starlette.websockets import WebSocketDisconnect

from voice_agent_web.main import create_app
from voice_agent_web.resource_models.conversation_resources import ConversationErrorMessage, ConversationStartedMessage, VoiceResource

GUEST_AUDIO_CHUNK: Final[bytes] = b"guest audio from the browser"
HTTP_OK_STATUS_CODE: Final[int] = 200
POLICY_VIOLATION_CLOSE_CODE: Final[int] = 1008


@pytest.fixture
def realtime_voice_service_scripted() -> Iterator[RealtimeVoiceServiceScripted]:
    with RealtimeVoiceServiceScripted() as realtime_voice_service_scripted:
        yield realtime_voice_service_scripted


@pytest.fixture
def test_client(realtime_voice_service_scripted: RealtimeVoiceServiceScripted, tmp_path: Path) -> Iterator[TestClient]:
    restaurant_database_path: Path = tmp_path / "restaurant.sqlite3"
    with TestClient(create_app(lambda: create_domain_facade(realtime_voice_service_scripted, restaurant_database_path))) as client:
        yield client


class TestVoiceAgentWebPipeline:
    def test_GetVoices_WhenRequested_ThenEveryVoiceComesBackInTheVoiceResourceShape(self, test_client: TestClient) -> None:
        expected_status_code: int = HTTP_OK_STATUS_CODE
        expected_voice_shapes: list[tuple[str, ...]] = [tuple(sorted(VoiceResource.__required_keys__))]

        actual_response: Response = test_client.get("/voices")

        actual_voices: list[dict[str, object]] = actual_response.json()["voices"]
        actual_voice_shapes: list[tuple[str, ...]] = sorted({tuple(sorted(actual_voice)) for actual_voice in actual_voices})
        assert (actual_response.status_code, actual_voice_shapes) == (expected_status_code, expected_voice_shapes)

    def test_GetRoot_WhenRequested_ThenTheMicrophonePageIsServed(self, test_client: TestClient) -> None:
        expected_status_code: int = HTTP_OK_STATUS_CODE
        expected_page_marker: str = 'id="call-button"'

        actual_response: Response = test_client.get("/")

        assert (actual_response.status_code, expected_page_marker in actual_response.text) == (expected_status_code, True)

    def test_Conversation_WhenTheBrowserConnectsAndTalks_ThenTheStartedMessageAgentSpeechAndTurnEndArriveInTheWireShape(
        self, test_client: TestClient
    ) -> None:
        expected_started_message_shape: list[str] = sorted(ConversationStartedMessage.__required_keys__)
        expected_started_message_type: str = "conversation_started"
        expected_agent_speech: bytes = SCRIPTED_GREETING_AUDIO
        expected_turn_finished_message: dict[str, object] = {"type": "agent_turn_finished"}

        with test_client.websocket_connect("/conversation?voice=openai-cedar") as websocket:
            actual_started_message: dict[str, object] = json.loads(websocket.receive_text())
            actual_agent_speech: bytes = websocket.receive_bytes()
            actual_turn_finished_message: dict[str, object] = json.loads(websocket.receive_text())
            websocket.send_bytes(GUEST_AUDIO_CHUNK)

        assert (sorted(actual_started_message), actual_started_message["type"], actual_agent_speech, actual_turn_finished_message) == (
            expected_started_message_shape,
            expected_started_message_type,
            expected_agent_speech,
            expected_turn_finished_message,
        )

    def test_Conversation_WhenTheVoiceIsNotOffered_ThenAnErrorMessageArrivesAndTheSocketClosesAsAPolicyViolation(
        self, test_client: TestClient
    ) -> None:
        expected_error_message_shape: list[str] = sorted(ConversationErrorMessage.__required_keys__)
        expected_error_message_type: str = "error"
        expected_close_code: int = POLICY_VIOLATION_CLOSE_CODE

        with test_client.websocket_connect("/conversation?voice=openai-nova") as websocket:
            actual_error_message: dict[str, object] = json.loads(websocket.receive_text())
            with pytest.raises(WebSocketDisconnect) as raised:
                websocket.receive_text()

        assert (sorted(actual_error_message), actual_error_message["type"], bool(actual_error_message["detail"]), raised.value.code) == (
            expected_error_message_shape,
            expected_error_message_type,
            True,
            expected_close_code,
        )
