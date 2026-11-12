# Handler tests for the browser's front door. They start at a handler method and end at its domain Hook, which
# ConversationHandlerForTest scripts, so no domain runs beneath them. They prove only what the handler owns: the wire
# request becomes the typed domain request, the guest's binary frames and cut-off reports become the guest side stream, the domain's
# answer becomes the browser's wire messages, a browser that hangs up ends the call quietly, and a domain failure or a
# frame that cannot be sent fails onward to the middleware untouched.

import json
import logging
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

import pytest
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import Message
from starlette.websockets import WebSocketDisconnect
from web_test_support.conversation_handler_for_test import ConversationHandlerForTest, GuestAudioReading
from web_test_support.generated_words import create_generated_word
from web_test_support.scripted_browser import ScriptedBrowser

from voice_agent_conversation import (
    AgentSpeechChunk,
    AgentSpeechCutOff,
    AgentToolCallAnswered,
    AgentToolCallOutcome,
    AgentTurnFinished,
    CallLimit,
    CallLimitReached,
    ConversationAudioFormat,
    ConversationEvent,
    ConversationRequest,
    ConversationStarted,
    GuestSideEvent,
    GuestSpeechChunk,
    GuestStartedSpeaking,
    PresentedGender,
    RealtimeVoiceProviderUnavailableException,
    SpeechProvider,
    SpeechProviderErrorTolerated,
    VoiceOption,
)
from voice_agent_conversation.managers.exceptions.realtime_voice_exceptions import LogEventRealtimeVoice

# The descriptions are incidental: the handler passes whatever the domain says.
CEDAR_VOICE_OPTION: Final[VoiceOption] = VoiceOption("openai-cedar", SpeechProvider.OPENAI, "cedar", PresentedGender.MALE, create_generated_word())
CORAL_VOICE_OPTION: Final[VoiceOption] = VoiceOption("openai-coral", SpeechProvider.OPENAI, "coral", PresentedGender.FEMALE, create_generated_word())
CONVERSATION_AUDIO_FORMAT: Final[ConversationAudioFormat] = ConversationAudioFormat(
    guest_audio_sample_rate_hz=16_000, agent_audio_sample_rate_hz=24_000
)
AGENT_SPEECH: Final[bytes] = b"agent speech pcm"
SCRIPTED_CONVERSATION_ID: Final[str] = secrets.token_hex(16)
NORMAL_CLOSURE_CODE: Final[int] = 1000
GOING_AWAY_CLOSE_CODE: Final[int] = 1001
ABNORMAL_CLOSURE_CODE: Final[int] = 1006
AGENT_SPEECH_CUT_OFF_MESSAGE_TYPE: Final[str] = "agent_speech_cut_off"
UNPLAYED_MILLISECONDS_FIELD_NAME: Final[str] = "unplayed_milliseconds"
HANDLER_LOGGER_NAME: Final[str] = "voice_agent_web.handlers.conversation_handler"
CALL_ENDED_EVENT: Final[str] = "call_ended"


def create_get_request(path: str) -> Request:
    return Request({"type": "http", "method": "GET", "path": path, "headers": [], "query_string": b""})


class TestConversationHandlerCheckHealth:
    async def test_CheckHealth_WhenTheDomainIsReady_ThenTheResponseSaysOkAfterAskingTheDomainOnce(self) -> None:
        conversation_handler_for_test: ConversationHandlerForTest = ConversationHandlerForTest()
        expected_status_code: int = 200
        expected_media_type: str = "application/json"
        expected_body: dict[str, object] = {"status": "ok"}
        expected_readiness_check_count: int = 1

        actual_response: Response = await conversation_handler_for_test.check_health(create_get_request("/healthz"))

        assert (
            actual_response.status_code,
            actual_response.media_type,
            json.loads(bytes(actual_response.body)),
            conversation_handler_for_test.captured_readiness_check_count,
        ) == (expected_status_code, expected_media_type, expected_body, expected_readiness_check_count)


class TestConversationHandlerListVoices:
    async def test_ListVoices_WhenTheDomainOffersVoices_ThenTheResponseCarriesEveryVoiceInTheVoiceResourceShape(self) -> None:
        conversation_handler_for_test: ConversationHandlerForTest = ConversationHandlerForTest(
            scripted_voice_options=[CEDAR_VOICE_OPTION, CORAL_VOICE_OPTION]
        )
        expected_status_code: int = 200
        expected_media_type: str = "application/json"
        expected_body: dict[str, object] = {
            "voices": [
                {"voice_key": "openai-cedar", "presented_gender": "male", "description": CEDAR_VOICE_OPTION.description},
                {"voice_key": "openai-coral", "presented_gender": "female", "description": CORAL_VOICE_OPTION.description},
            ]
        }

        actual_response: Response = await conversation_handler_for_test.list_voices(create_get_request("/voices"))

        assert (actual_response.status_code, actual_response.media_type, json.loads(bytes(actual_response.body))) == (
            expected_status_code,
            expected_media_type,
            expected_body,
        )


@dataclass(frozen=True)
class LoggedCallSummary:
    """One logged call summary as a test reads it back, without the call's length, which a test cannot know."""

    event: str
    conversation_id: str | None
    voice_key: str | None
    ending: str
    agent_tool_calls: Mapping[str, Mapping[str, int]]


def read_call_summaries(caplog: pytest.LogCaptureFixture) -> list[LoggedCallSummary]:
    logged_call_summaries: list[LoggedCallSummary] = []
    log_record: logging.LogRecord
    for log_record in caplog.records:
        event_fields: object = getattr(log_record, "event_fields", None)
        if log_record.name == HANDLER_LOGGER_NAME and isinstance(event_fields, dict) and event_fields.get("event") == CALL_ENDED_EVENT:
            logged_call_summaries.append(
                LoggedCallSummary(
                    event=event_fields["event"],
                    conversation_id=event_fields["conversation_id"],
                    voice_key=event_fields["voice_key"],
                    ending=event_fields["ending"],
                    agent_tool_calls=event_fields["agent_tool_calls"],
                )
            )
    return logged_call_summaries


class TestConversationHandlerHoldConversation:
    async def test_HoldConversation_WhenTheBrowserAsksForAVoiceAndTalks_ThenTheDomainGetsTheVoiceVerbatimAndOnlyTheBinaryFramesAsGuestAudio(
        self,
    ) -> None:
        guest_audio_chunks: list[bytes] = [b"guest audio one", b"guest audio two"]
        scripted_browser: ScriptedBrowser = ScriptedBrowser(
            query_string=b"voice=%20%20OpenAI-Cedar%20",
            browser_messages=[
                {"type": "websocket.receive", "bytes": guest_audio_chunks[0]},
                {"type": "websocket.receive", "text": "a text frame the call does not need"},
                {"type": "websocket.receive", "bytes": guest_audio_chunks[1]},
                {"type": "websocket.disconnect", "code": NORMAL_CLOSURE_CODE},
            ],
        )
        conversation_handler_for_test: ConversationHandlerForTest = ConversationHandlerForTest(
            guest_audio_reading=GuestAudioReading.READ_AFTER_THE_EVENTS
        )
        expected_conversation_request: ConversationRequest = ConversationRequest(voice_key="  OpenAI-Cedar ")
        expected_guest_side_events: list[GuestSideEvent] = [GuestSpeechChunk(pcm_audio=guest_audio_chunk) for guest_audio_chunk in guest_audio_chunks]
        expected_delivered_messages: list[Message] = [{"type": "websocket.accept", "subprotocol": None, "headers": []}]

        await conversation_handler_for_test.hold_conversation(scripted_browser.create_websocket())

        assert (
            conversation_handler_for_test.captured_conversation_request,
            conversation_handler_for_test.captured_guest_side_events,
            scripted_browser.delivered_messages,
        ) == (expected_conversation_request, expected_guest_side_events, expected_delivered_messages)

    async def test_HoldConversation_WhenThePageReportsAgentSpeechCutOff_ThenTheDomainGetsHowMuchWentUnplayedAndInvalidReportsArePassedOver(
        self,
    ) -> None:
        unplayed_milliseconds: int = 640
        scripted_browser: ScriptedBrowser = ScriptedBrowser(
            query_string=b"voice=openai-cedar",
            browser_messages=[
                {
                    "type": "websocket.receive",
                    "text": json.dumps({"type": AGENT_SPEECH_CUT_OFF_MESSAGE_TYPE, UNPLAYED_MILLISECONDS_FIELD_NAME: unplayed_milliseconds}),
                },
                {
                    "type": "websocket.receive",
                    "text": json.dumps({"type": AGENT_SPEECH_CUT_OFF_MESSAGE_TYPE, UNPLAYED_MILLISECONDS_FIELD_NAME: "a lot"}),
                },
                {
                    "type": "websocket.receive",
                    "text": json.dumps({"type": AGENT_SPEECH_CUT_OFF_MESSAGE_TYPE, UNPLAYED_MILLISECONDS_FIELD_NAME: True}),
                },
                {"type": "websocket.receive", "text": json.dumps({"type": AGENT_SPEECH_CUT_OFF_MESSAGE_TYPE, UNPLAYED_MILLISECONDS_FIELD_NAME: -5})},
                {"type": "websocket.receive", "text": json.dumps({"type": "guest_started_speaking", UNPLAYED_MILLISECONDS_FIELD_NAME: 5})},
                {"type": "websocket.receive", "text": "{not json"},
                {"type": "websocket.disconnect", "code": NORMAL_CLOSURE_CODE},
            ],
        )
        conversation_handler_for_test: ConversationHandlerForTest = ConversationHandlerForTest(
            guest_audio_reading=GuestAudioReading.READ_AFTER_THE_EVENTS
        )
        expected_guest_side_events: list[GuestSideEvent] = [AgentSpeechCutOff(unplayed_milliseconds=unplayed_milliseconds)]

        await conversation_handler_for_test.hold_conversation(scripted_browser.create_websocket())

        assert conversation_handler_for_test.captured_guest_side_events == expected_guest_side_events

    async def test_HoldConversation_WhenTheDomainYieldsEveryKindOfEvent_ThenTheBrowserGetsEachAsItsWireFrameInOrderAndThenTheClose(self) -> None:
        scripted_conversation_events: list[ConversationEvent] = [
            ConversationStarted(
                conversation_id=SCRIPTED_CONVERSATION_ID, conversation_audio_format=CONVERSATION_AUDIO_FORMAT, voice_option=CEDAR_VOICE_OPTION
            ),
            AgentSpeechChunk(pcm_audio=AGENT_SPEECH),
            GuestStartedSpeaking(),
            AgentTurnFinished(),
            CallLimitReached(call_limit=CallLimit.MAXIMUM_DURATION),
        ]
        scripted_browser: ScriptedBrowser = ScriptedBrowser(query_string=b"voice=openai-cedar")
        conversation_handler_for_test: ConversationHandlerForTest = ConversationHandlerForTest(
            scripted_conversation_events=scripted_conversation_events
        )
        expected_call_limit_text: str = json.dumps(
            {
                "type": "call_limit_reached",
                "call_limit": "maximum_duration",
                "detail": "The call reached its time limit. You're welcome to call again.",
            }
        )
        expected_started_text: str = json.dumps(
            {
                "type": "conversation_started",
                "conversation_id": SCRIPTED_CONVERSATION_ID,
                "guest_audio_sample_rate_hz": 16_000,
                "agent_audio_sample_rate_hz": 24_000,
                "voice": {"voice_key": "openai-cedar", "presented_gender": "male", "description": CEDAR_VOICE_OPTION.description},
            }
        )
        expected_delivered_messages: list[Message] = [
            {"type": "websocket.accept", "subprotocol": None, "headers": []},
            {"type": "websocket.send", "text": expected_started_text},
            {"type": "websocket.send", "bytes": AGENT_SPEECH},
            {"type": "websocket.send", "text": json.dumps({"type": "guest_started_speaking"})},
            {"type": "websocket.send", "text": json.dumps({"type": "agent_turn_finished"})},
            {"type": "websocket.send", "text": expected_call_limit_text},
            {"type": "websocket.close", "code": NORMAL_CLOSURE_CODE},
        ]

        await conversation_handler_for_test.hold_conversation(scripted_browser.create_websocket())

        assert scripted_browser.delivered_messages == expected_delivered_messages

    async def test_HoldConversation_WhenTheDomainReportsAToleratedProviderError_ThenItIsLoggedAsAWarningAndNeverSentToTheBrowser(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        speech_provider_error_tolerated: SpeechProviderErrorTolerated = SpeechProviderErrorTolerated(
            error_type=create_generated_word(), error_code=create_generated_word(), error_message=create_generated_word()
        )
        scripted_browser: ScriptedBrowser = ScriptedBrowser(query_string=b"voice=openai-cedar")
        conversation_handler_for_test: ConversationHandlerForTest = ConversationHandlerForTest(
            scripted_conversation_events=[speech_provider_error_tolerated, AgentTurnFinished()]
        )
        expected_delivered_messages: list[Message] = [
            {"type": "websocket.accept", "subprotocol": None, "headers": []},
            {"type": "websocket.send", "text": json.dumps({"type": "agent_turn_finished"})},
            {"type": "websocket.close", "code": NORMAL_CLOSURE_CODE},
        ]
        expected_logged_values: list[tuple[int, bool]] = [(logging.WARNING, True)]

        with caplog.at_level(logging.WARNING, logger=HANDLER_LOGGER_NAME):
            await conversation_handler_for_test.hold_conversation(scripted_browser.create_websocket())

        actual_logged_values: list[tuple[int, bool]] = [
            (
                log_record.levelno,
                all(
                    tolerated_error_value in log_record.getMessage()
                    for tolerated_error_value in (
                        speech_provider_error_tolerated.error_type,
                        speech_provider_error_tolerated.error_code,
                        speech_provider_error_tolerated.error_message,
                    )
                ),
            )
            for log_record in caplog.records
            if log_record.name == HANDLER_LOGGER_NAME
        ]
        assert (scripted_browser.delivered_messages, actual_logged_values) == (expected_delivered_messages, expected_logged_values)

    async def test_HoldConversation_WhenTheBrowserHangsUpBeforeTheFirstFrame_ThenNothingMoreIsSentAndTheCallEndsWithoutAFailure(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        scripted_conversation_events: list[ConversationEvent] = [
            ConversationStarted(
                conversation_id=SCRIPTED_CONVERSATION_ID, conversation_audio_format=CONVERSATION_AUDIO_FORMAT, voice_option=CEDAR_VOICE_OPTION
            ),
            AgentSpeechChunk(pcm_audio=AGENT_SPEECH),
            AgentTurnFinished(),
        ]
        scripted_browser: ScriptedBrowser = ScriptedBrowser(
            query_string=b"voice=openai-cedar", browser_messages=[{"type": "websocket.disconnect", "code": GOING_AWAY_CLOSE_CODE}]
        )
        conversation_handler_for_test: ConversationHandlerForTest = ConversationHandlerForTest(
            scripted_conversation_events=scripted_conversation_events, guest_audio_reading=GuestAudioReading.READ_BEFORE_THE_EVENTS
        )
        expected_delivered_message_types: list[str] = ["websocket.accept"]
        expected_call_summaries: list[LoggedCallSummary] = [
            LoggedCallSummary(
                event=CALL_ENDED_EVENT,
                conversation_id=SCRIPTED_CONVERSATION_ID,
                voice_key="openai-cedar",
                ending="hung_up",
                agent_tool_calls={},
            )
        ]

        with caplog.at_level(logging.INFO, logger=HANDLER_LOGGER_NAME):
            await conversation_handler_for_test.hold_conversation(scripted_browser.create_websocket())

        actual_delivered_message_types: list[str] = [delivered_message["type"] for delivered_message in scripted_browser.delivered_messages]
        assert (actual_delivered_message_types, read_call_summaries(caplog)) == (expected_delivered_message_types, expected_call_summaries)

    async def test_HoldConversation_WhenAFrameCannotBeSent_ThenTheFailurePassesUntouchedToTheMiddleware(self) -> None:
        # The connection is gone but no disconnect has been read, so the handler still believes the browser is there.
        scripted_conversation_events: list[ConversationEvent] = [
            ConversationStarted(
                conversation_id=SCRIPTED_CONVERSATION_ID, conversation_audio_format=CONVERSATION_AUDIO_FORMAT, voice_option=CEDAR_VOICE_OPTION
            )
        ]
        scripted_browser: ScriptedBrowser = ScriptedBrowser(query_string=b"voice=openai-cedar", connection_is_lost=True)
        conversation_handler_for_test: ConversationHandlerForTest = ConversationHandlerForTest(
            scripted_conversation_events=scripted_conversation_events
        )
        expected_refused_message_types: list[str] = ["websocket.send"]
        expected_close_code: int = ABNORMAL_CLOSURE_CODE

        with pytest.raises(WebSocketDisconnect) as raised:
            await conversation_handler_for_test.hold_conversation(scripted_browser.create_websocket())

        actual_refused_message_types: list[str] = [refused_message["type"] for refused_message in scripted_browser.refused_messages]
        assert (actual_refused_message_types, raised.value.code) == (expected_refused_message_types, expected_close_code)

    async def test_HoldConversation_WhenTheDomainFailsMidCall_ThenThatSameFailurePassesUntouchedToTheMiddleware(self) -> None:
        scripted_realtime_voice_provider_unavailable_exception: RealtimeVoiceProviderUnavailableException = RealtimeVoiceProviderUnavailableException(
            "The provider dropped the session mid-call.", LogEventRealtimeVoice.EVENT_RECEIPT, {"RealtimeVoice.Operation": "receiving events"}
        )
        scripted_browser: ScriptedBrowser = ScriptedBrowser(query_string=b"voice=openai-cedar")
        conversation_handler_for_test: ConversationHandlerForTest = ConversationHandlerForTest(
            scripted_conversation_events=[
                ConversationStarted(
                    conversation_id=SCRIPTED_CONVERSATION_ID, conversation_audio_format=CONVERSATION_AUDIO_FORMAT, voice_option=CEDAR_VOICE_OPTION
                )
            ],
            scripted_conversation_failure=scripted_realtime_voice_provider_unavailable_exception,
        )
        expected_contextual_data_by_name: dict[str, str | int | float | bool] = dict(
            scripted_realtime_voice_provider_unavailable_exception.contextual_data_by_name
        )
        expected_delivered_message_types: list[str] = ["websocket.accept", "websocket.send"]

        with pytest.raises(RealtimeVoiceProviderUnavailableException) as raised:
            await conversation_handler_for_test.hold_conversation(scripted_browser.create_websocket())

        actual_delivered_message_types: list[str] = [delivered_message["type"] for delivered_message in scripted_browser.delivered_messages]
        assert (
            raised.value is scripted_realtime_voice_provider_unavailable_exception,
            raised.value.contextual_data_by_name,
            actual_delivered_message_types,
        ) == (
            True,
            expected_contextual_data_by_name,
            expected_delivered_message_types,
        )

    async def test_HoldConversation_WhenACallEnds_ThenOneSummaryNamesTheConversationHowItEndedAndTheToolCallsButNotThePage(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        availability_tool_name: str = "check_availability"
        booking_tool_name: str = "book_table"
        scripted_conversation_events: list[ConversationEvent] = [
            ConversationStarted(
                conversation_id=SCRIPTED_CONVERSATION_ID, conversation_audio_format=CONVERSATION_AUDIO_FORMAT, voice_option=CEDAR_VOICE_OPTION
            ),
            AgentToolCallAnswered(tool_name=availability_tool_name, agent_tool_call_outcome=AgentToolCallOutcome.CORRECTED),
            AgentToolCallAnswered(tool_name=availability_tool_name, agent_tool_call_outcome=AgentToolCallOutcome.ANSWERED),
            AgentToolCallAnswered(tool_name=booking_tool_name, agent_tool_call_outcome=AgentToolCallOutcome.ANSWERED),
            CallLimitReached(call_limit=CallLimit.MAXIMUM_DURATION),
        ]
        scripted_browser: ScriptedBrowser = ScriptedBrowser(query_string=b"voice=openai-cedar")
        conversation_handler_for_test: ConversationHandlerForTest = ConversationHandlerForTest(
            scripted_conversation_events=scripted_conversation_events
        )
        expected_delivered_message_types: list[str] = ["websocket.accept", "websocket.send", "websocket.send", "websocket.close"]
        expected_call_summaries: list[LoggedCallSummary] = [
            LoggedCallSummary(
                event=CALL_ENDED_EVENT,
                conversation_id=SCRIPTED_CONVERSATION_ID,
                voice_key="openai-cedar",
                ending="call_limit:maximum_duration",
                agent_tool_calls={availability_tool_name: {"corrected": 1, "answered": 1}, booking_tool_name: {"answered": 1}},
            )
        ]

        with caplog.at_level(logging.INFO, logger=HANDLER_LOGGER_NAME):
            await conversation_handler_for_test.hold_conversation(scripted_browser.create_websocket())

        actual_delivered_message_types: list[str] = [delivered_message["type"] for delivered_message in scripted_browser.delivered_messages]
        assert (actual_delivered_message_types, read_call_summaries(caplog)) == (expected_delivered_message_types, expected_call_summaries)

    async def test_HoldConversation_WhenTheDomainFailsMidCall_ThenTheCallSummarySaysTheCallFailed(self, caplog: pytest.LogCaptureFixture) -> None:
        scripted_browser: ScriptedBrowser = ScriptedBrowser(query_string=b"voice=openai-cedar")
        conversation_handler_for_test: ConversationHandlerForTest = ConversationHandlerForTest(
            scripted_conversation_events=[
                ConversationStarted(
                    conversation_id=SCRIPTED_CONVERSATION_ID, conversation_audio_format=CONVERSATION_AUDIO_FORMAT, voice_option=CEDAR_VOICE_OPTION
                )
            ],
            scripted_conversation_failure=RealtimeVoiceProviderUnavailableException(
                "The provider dropped the session.", LogEventRealtimeVoice.EVENT_RECEIPT
            ),
        )
        expected_call_summaries: list[LoggedCallSummary] = [
            LoggedCallSummary(
                event=CALL_ENDED_EVENT,
                conversation_id=SCRIPTED_CONVERSATION_ID,
                voice_key="openai-cedar",
                ending="failed",
                agent_tool_calls={},
            )
        ]

        with caplog.at_level(logging.INFO, logger=HANDLER_LOGGER_NAME), pytest.raises(RealtimeVoiceProviderUnavailableException):
            await conversation_handler_for_test.hold_conversation(scripted_browser.create_websocket())

        assert read_call_summaries(caplog) == expected_call_summaries
