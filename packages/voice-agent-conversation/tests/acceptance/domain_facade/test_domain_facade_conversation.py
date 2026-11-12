# Acceptance tests for voice conversations, black-box through the conversation DomainFacade.
# The real speech gateway talks over a real WebSocket to a scripted Realtime service on this machine, so the
# gateway, its session and its exception translator run in every test. The restaurant behind the agent's
# briefing is real, with a fixed clock. Every conversation must end within a time limit: a conversation that
# never ends fails as a timeout instead of hanging the suite.

import asyncio
from contextlib import aclosing
from dataclasses import dataclass
from datetime import datetime
from http import HTTPStatus
from pathlib import Path
from typing import Final

import pytest
from conversation_acceptance_support.asserters.asserter_conversation import AsserterConversation
from conversation_acceptance_support.asserters.asserter_exception import AsserterException, ExpectedExceptionContent, ExpectedExceptionMetadata
from conversation_acceptance_support.bundled_voice_catalog import read_catalog_voice_option, read_catalog_voice_options
from conversation_acceptance_support.guest_microphone import GuestMicrophone, GuestMicrophoneBreakdownException
from conversation_acceptance_support.realtime_voice_service_scripted import (
    SCRIPTED_GREETING_AUDIO,
    CapturedAgentSpeechTruncation,
    ErrorEventMessage,
    RealtimeVoiceServiceScripted,
    ScriptedServerEventMessage,
    create_agent_speech_event,
    create_error_event,
    create_failed_response_event,
    create_malformed_agent_speech_event,
    create_speech_started_event,
)
from conversation_acceptance_support.service_locator_testing import (
    SCRIPTED_SERVICE_API_KEY,
    TESTING_REALTIME_MODEL,
    create_domain_facade,
    create_restaurant_domain_facade,
)

from voice_agent_conversation import (
    AgentSpeechChunk,
    AgentTurnFinished,
    ConversationAudioFormat,
    ConversationEvent,
    ConversationRequest,
    ConversationRequestValidationException,
    ConversationStarted,
    DomainFacade,
    ExceptionAction,
    GuestStartedSpeaking,
    LogEventConversation,
    LogEventRealtimeVoice,
    PresentedGender,
    RealtimeVoiceProviderAccessDeniedException,
    RealtimeVoiceProviderErrorException,
    RealtimeVoiceProviderUnavailableException,
    RealtimeVoiceSessionExpiredException,
    Severity,
    SpeechProviderErrorTolerated,
    VoiceAgentConversationBaseException,
    VoiceNotOfferedException,
    VoiceOption,
)

CEDAR_VOICE_OPTION: Final[VoiceOption] = read_catalog_voice_option("openai-cedar")
PROVIDER_AUDIO_FORMAT: Final[ConversationAudioFormat] = ConversationAudioFormat(guest_audio_sample_rate_hz=24_000, agent_audio_sample_rate_hz=24_000)
GUEST_AUDIO_CHUNKS: Final[list[bytes]] = [b"guest audio chunk one", b"guest audio chunk two"]
# One second of the agent's reply: mono 16-bit PCM at the provider's rate.
AGENT_REPLY_SPEECH_MILLISECONDS: Final[int] = 1_000
AGENT_REPLY_SPEECH: Final[bytes] = bytes(PROVIDER_AUDIO_FORMAT.agent_audio_sample_rate_hz * 2)
AGENT_REPLY_ITEM_ID: Final[str] = "item_reply"
# ConversationStarted, the greeting's speech, the end of its turn, the reply's speech and the guest talking over it.
TALKED_OVER_EVENT_COUNT: Final[int] = 5
CONVERSATION_TIME_LIMIT_SECONDS: Final[float] = 5.0
BUSINESS_REFUSAL_HTTP_STATUS_CODE: Final[int] = 400
NOT_FOUND_HTTP_STATUS_CODE: Final[int] = 404
TECHNICAL_FAILURE_HTTP_STATUS_CODE: Final[int] = 500
PROVIDER_ERROR_HTTP_STATUS_CODE: Final[int] = 502
SERVICE_UNAVAILABLE_HTTP_STATUS_CODE: Final[int] = 503
PROVIDER_UNAVAILABLE_REASON: Final[str] = "The voice service is temporarily unavailable"
PROVIDER_ACCESS_DENIED_REASON: Final[str] = "The voice service refused access"
OPERATION_CONTEXT_NAME: Final[str] = "RealtimeVoice.Operation"
PROVIDER_ERROR_TYPE_CONTEXT_NAME: Final[str] = "RealtimeVoice.ProviderErrorType"
PROVIDER_ERROR_CODE_CONTEXT_NAME: Final[str] = "RealtimeVoice.ProviderErrorCode"
PROVIDER_ERROR_MESSAGE_CONTEXT_NAME: Final[str] = "RealtimeVoice.ProviderErrorMessage"
CONNECT_OPERATION: Final[str] = f"connecting to model '{TESTING_REALTIME_MODEL}'"


@dataclass(frozen=True)
class ProviderFailureScenario:
    scripted_server_event_message: ScriptedServerEventMessage
    expected_exception_type: type[VoiceAgentConversationBaseException]
    expected_exception_content: ExpectedExceptionContent


def describe_spoken_local_now(restaurant_local_now: datetime) -> str:
    # How a host would say the restaurant's date and time aloud, without zero padding.
    spoken_hour: int = restaurant_local_now.hour % 12 or 12
    return (
        f"{restaurant_local_now:%A, %B} {restaurant_local_now.day}, {restaurant_local_now.year}, "
        f"at {spoken_hour}:{restaurant_local_now:%M} {restaurant_local_now:%p}"
    )


class TestConversation:
    async def test_Converse_WhenTheGuestCallsAndHangsUp_ThenTheCallStartsInTheChosenVoiceTheAgentGreetsAndTheGuestAudioReachesTheProvider(
        self, restaurant_database_path: Path
    ) -> None:
        guest_microphone: GuestMicrophone = GuestMicrophone()
        conversation_request: ConversationRequest = ConversationRequest(voice_key=CEDAR_VOICE_OPTION.voice_key)
        expected_conversation_events: list[ConversationEvent] = [
            ConversationStarted(conversation_audio_format=PROVIDER_AUDIO_FORMAT, voice_option=CEDAR_VOICE_OPTION),
            AgentSpeechChunk(pcm_audio=SCRIPTED_GREETING_AUDIO),
            AgentTurnFinished(),
        ]
        expected_agent_response_request_count: int = 1

        async with (
            RealtimeVoiceServiceScripted() as realtime_voice_service_scripted,
            create_domain_facade(realtime_voice_service_scripted, restaurant_database_path) as domain_facade,
            asyncio.timeout(CONVERSATION_TIME_LIMIT_SECONDS),
            aclosing(domain_facade.converse(conversation_request, guest_microphone.stream_guest_side_events())) as conversation,
        ):
            actual_conversation_events: list[ConversationEvent] = await guest_microphone.take_part(conversation, GUEST_AUDIO_CHUNKS)

        AsserterConversation.assert_call_is_as_expected(
            expected_conversation_events=expected_conversation_events,
            expected_guest_audio=GUEST_AUDIO_CHUNKS,
            expected_agent_response_request_count=expected_agent_response_request_count,
            actual_conversation_events=actual_conversation_events,
            actual_captured_realtime_sessions=realtime_voice_service_scripted.captured_realtime_sessions,
        )

    async def test_Converse_WhenAConversationStarts_ThenTheAgentIsBriefedWithTheRestaurantAndItsLocalDateAndTimeInTheChosenVoice(
        self, restaurant_database_path: Path
    ) -> None:
        async with create_restaurant_domain_facade(restaurant_database_path) as restaurant_domain_facade:
            restaurant_name: str = (await restaurant_domain_facade.get_restaurant_profile()).name
            restaurant_local_now: datetime = await restaurant_domain_facade.get_restaurant_local_now()
        guest_microphone: GuestMicrophone = GuestMicrophone()
        conversation_request: ConversationRequest = ConversationRequest(voice_key=CEDAR_VOICE_OPTION.voice_key)
        expected_provider_voice_id: str = CEDAR_VOICE_OPTION.provider_voice_id
        expected_instruction_phrases: list[str] = [restaurant_name, describe_spoken_local_now(restaurant_local_now)]

        async with (
            RealtimeVoiceServiceScripted() as realtime_voice_service_scripted,
            create_domain_facade(realtime_voice_service_scripted, restaurant_database_path) as domain_facade,
            asyncio.timeout(CONVERSATION_TIME_LIMIT_SECONDS),
            aclosing(domain_facade.converse(conversation_request, guest_microphone.stream_guest_side_events())) as conversation,
        ):
            await guest_microphone.take_part(conversation, [])

        AsserterConversation.assert_agent_briefing_is_as_expected(
            expected_provider_voice_id=expected_provider_voice_id,
            expected_instruction_phrases=expected_instruction_phrases,
            actual_captured_realtime_sessions=realtime_voice_service_scripted.captured_realtime_sessions,
        )

    async def test_Converse_WhenTheGuestTalksOverTheAgent_ThenTheHostIsToldToStopPlayback(self, restaurant_database_path: Path) -> None:
        guest_microphone: GuestMicrophone = GuestMicrophone()
        conversation_request: ConversationRequest = ConversationRequest(voice_key=CEDAR_VOICE_OPTION.voice_key)
        expected_conversation_events: list[ConversationEvent] = [
            ConversationStarted(conversation_audio_format=PROVIDER_AUDIO_FORMAT, voice_option=CEDAR_VOICE_OPTION),
            AgentSpeechChunk(pcm_audio=SCRIPTED_GREETING_AUDIO),
            AgentTurnFinished(),
            GuestStartedSpeaking(),
        ]

        async with (
            RealtimeVoiceServiceScripted(events_after_each_guest_audio=[create_speech_started_event()]) as realtime_voice_service_scripted,
            create_domain_facade(realtime_voice_service_scripted, restaurant_database_path) as domain_facade,
            asyncio.timeout(CONVERSATION_TIME_LIMIT_SECONDS),
            aclosing(domain_facade.converse(conversation_request, guest_microphone.stream_guest_side_events())) as conversation,
        ):
            actual_conversation_events: list[ConversationEvent] = await guest_microphone.take_part(
                conversation, GUEST_AUDIO_CHUNKS[:1], hang_up_after_event_count=len(expected_conversation_events)
            )

        AsserterConversation.assert_conversation_events_are_as_expected(
            expected_conversation_events=expected_conversation_events, actual_conversation_events=actual_conversation_events
        )

    async def test_Converse_WhenTheProviderRefusesAReplyRequestBecauseAReplyIsUnderWay_ThenTheCallGoesOnAndTheHostIsGivenTheErrorToLog(
        self, restaurant_database_path: Path
    ) -> None:
        # A reply asked for after tool calls can meet the reply the provider began itself when the guest spoke.
        guest_microphone: GuestMicrophone = GuestMicrophone()
        conversation_request: ConversationRequest = ConversationRequest(voice_key=CEDAR_VOICE_OPTION.voice_key)
        active_response_refusal: ErrorEventMessage = create_error_event(
            "invalid_request_error", "conversation_already_has_active_response", "Conversation already has an active response in progress."
        )
        expected_conversation_events: list[ConversationEvent] = [
            ConversationStarted(conversation_audio_format=PROVIDER_AUDIO_FORMAT, voice_option=CEDAR_VOICE_OPTION),
            AgentSpeechChunk(pcm_audio=SCRIPTED_GREETING_AUDIO),
            AgentTurnFinished(),
            SpeechProviderErrorTolerated(
                error_type=active_response_refusal["error"]["type"],
                error_code=active_response_refusal["error"]["code"],
                error_message=active_response_refusal["error"]["message"],
            ),
            GuestStartedSpeaking(),
        ]

        async with (
            RealtimeVoiceServiceScripted(
                events_after_each_guest_audio=[active_response_refusal, create_speech_started_event()]
            ) as realtime_voice_service_scripted,
            create_domain_facade(realtime_voice_service_scripted, restaurant_database_path) as domain_facade,
            asyncio.timeout(CONVERSATION_TIME_LIMIT_SECONDS),
            aclosing(domain_facade.converse(conversation_request, guest_microphone.stream_guest_side_events())) as conversation,
        ):
            actual_conversation_events: list[ConversationEvent] = await guest_microphone.take_part(
                conversation, GUEST_AUDIO_CHUNKS[:1], hang_up_after_event_count=len(expected_conversation_events)
            )

        AsserterConversation.assert_conversation_events_are_as_expected(
            expected_conversation_events=expected_conversation_events, actual_conversation_events=actual_conversation_events
        )

    async def test_Converse_WhenTheGuestTalksOverTheAgent_ThenTheProviderForgetsTheSpeechTheGuestDidNotHear(
        self, restaurant_database_path: Path
    ) -> None:
        guest_microphone: GuestMicrophone = GuestMicrophone()
        conversation_request: ConversationRequest = ConversationRequest(voice_key=CEDAR_VOICE_OPTION.voice_key)
        unplayed_milliseconds: int = 600
        expected_agent_speech_truncations: list[CapturedAgentSpeechTruncation] = [
            CapturedAgentSpeechTruncation(
                item_id=AGENT_REPLY_ITEM_ID, content_index=0, audio_end_ms=AGENT_REPLY_SPEECH_MILLISECONDS - unplayed_milliseconds
            )
        ]

        async with (
            RealtimeVoiceServiceScripted(
                events_after_each_guest_audio=[create_agent_speech_event(AGENT_REPLY_ITEM_ID, AGENT_REPLY_SPEECH), create_speech_started_event()]
            ) as realtime_voice_service_scripted,
            create_domain_facade(realtime_voice_service_scripted, restaurant_database_path) as domain_facade,
            asyncio.timeout(CONVERSATION_TIME_LIMIT_SECONDS),
            aclosing(domain_facade.converse(conversation_request, guest_microphone.stream_guest_side_events())) as conversation,
        ):
            await guest_microphone.take_part(
                conversation,
                GUEST_AUDIO_CHUNKS[:1],
                hang_up_after_event_count=TALKED_OVER_EVENT_COUNT,
                unplayed_milliseconds_when_talked_over=unplayed_milliseconds,
            )

        actual_agent_speech_truncations: list[CapturedAgentSpeechTruncation] = realtime_voice_service_scripted.captured_realtime_sessions[
            0
        ].agent_speech_truncations
        assert actual_agent_speech_truncations == expected_agent_speech_truncations

    async def test_Converse_WhenTheHostDroppedMoreSpeechThanTheReplyHolds_ThenTheProviderForgetsTheWholeReply(
        self, restaurant_database_path: Path
    ) -> None:
        guest_microphone: GuestMicrophone = GuestMicrophone()
        conversation_request: ConversationRequest = ConversationRequest(voice_key=CEDAR_VOICE_OPTION.voice_key)
        # The host's queue also held the end of the greeting, so it dropped more than the reply alone.
        unplayed_milliseconds: int = AGENT_REPLY_SPEECH_MILLISECONDS + 250
        expected_agent_speech_truncations: list[CapturedAgentSpeechTruncation] = [
            CapturedAgentSpeechTruncation(item_id=AGENT_REPLY_ITEM_ID, content_index=0, audio_end_ms=0)
        ]

        async with (
            RealtimeVoiceServiceScripted(
                events_after_each_guest_audio=[create_agent_speech_event(AGENT_REPLY_ITEM_ID, AGENT_REPLY_SPEECH), create_speech_started_event()]
            ) as realtime_voice_service_scripted,
            create_domain_facade(realtime_voice_service_scripted, restaurant_database_path) as domain_facade,
            asyncio.timeout(CONVERSATION_TIME_LIMIT_SECONDS),
            aclosing(domain_facade.converse(conversation_request, guest_microphone.stream_guest_side_events())) as conversation,
        ):
            await guest_microphone.take_part(
                conversation,
                GUEST_AUDIO_CHUNKS[:1],
                hang_up_after_event_count=TALKED_OVER_EVENT_COUNT,
                unplayed_milliseconds_when_talked_over=unplayed_milliseconds,
            )

        actual_agent_speech_truncations: list[CapturedAgentSpeechTruncation] = realtime_voice_service_scripted.captured_realtime_sessions[
            0
        ].agent_speech_truncations
        assert actual_agent_speech_truncations == expected_agent_speech_truncations

    async def test_Converse_WhenTheVoiceKeyHasStraySpacesAndCapitals_ThenTheCallStartsInThatVoice(self, restaurant_database_path: Path) -> None:
        guest_microphone: GuestMicrophone = GuestMicrophone()
        conversation_request: ConversationRequest = ConversationRequest(voice_key="  OpenAI-Marin ")
        expected_conversation_started: ConversationStarted = ConversationStarted(
            conversation_audio_format=PROVIDER_AUDIO_FORMAT, voice_option=read_catalog_voice_option("openai-marin")
        )

        async with (
            RealtimeVoiceServiceScripted() as realtime_voice_service_scripted,
            create_domain_facade(realtime_voice_service_scripted, restaurant_database_path) as domain_facade,
            asyncio.timeout(CONVERSATION_TIME_LIMIT_SECONDS),
            aclosing(domain_facade.converse(conversation_request, guest_microphone.stream_guest_side_events())) as conversation,
        ):
            actual_conversation_started: ConversationEvent = await anext(conversation)

        assert actual_conversation_started == expected_conversation_started

    async def test_Converse_WhenTheVoiceIsNotInTheCatalog_ThenTheRefusalNamesTheOfferedVoicesAndTheProviderIsNeverCalled(
        self, restaurant_database_path: Path
    ) -> None:
        guest_microphone: GuestMicrophone = GuestMicrophone()
        refused_voice_key: str = "openai-nova"
        conversation_request: ConversationRequest = ConversationRequest(voice_key=refused_voice_key)
        expected_offered_voice_keys: list[str] = [voice_option.voice_key for voice_option in read_catalog_voice_options()]
        expected_exception_content: ExpectedExceptionContent = ExpectedExceptionContent(
            message_phrases=[refused_voice_key, *expected_offered_voice_keys],
            expected_exception_metadata=ExpectedExceptionMetadata(
                http_status_code=NOT_FOUND_HTTP_STATUS_CODE,
                exception_action=ExceptionAction.USER_ACTION_REQUIRED,
                reason="The requested voice is not offered",
                severity=Severity.ERROR,
                log_event=LogEventConversation.CONVERSATION_START,
            ),
            contextual_data_by_name={"Conversation.RequestedVoiceKey": refused_voice_key},
        )
        expected_provider_session_count: int = 0

        async with (
            RealtimeVoiceServiceScripted() as realtime_voice_service_scripted,
            create_domain_facade(realtime_voice_service_scripted, restaurant_database_path) as domain_facade,
            aclosing(domain_facade.converse(conversation_request, guest_microphone.stream_guest_side_events())) as conversation,
        ):
            with pytest.raises(VoiceNotOfferedException) as raised:
                await anext(conversation)

        AsserterException.assert_voice_not_offered_refusal_is_as_expected(
            expected_offered_voice_keys=expected_offered_voice_keys,
            expected_exception_content=expected_exception_content,
            expected_provider_session_count=expected_provider_session_count,
            actual_voice_not_offered_exception=raised.value,
            actual_captured_realtime_sessions=realtime_voice_service_scripted.captured_realtime_sessions,
        )

    @pytest.mark.parametrize(
        ("voice_key", "expected_problem_phrase"),
        [
            (None, "A voice is required."),
            ("   ", "A voice is required."),
            ("openai marin!", "'openai marin!' may contain only letters, digits and single hyphens"),
        ],
    )
    async def test_Converse_WhenTheVoiceKeyIsMissingOrMalformed_ThenTheRequestIsRefusedBeforeTheProviderIsCalled(
        self, restaurant_database_path: Path, voice_key: str | None, expected_problem_phrase: str
    ) -> None:
        guest_microphone: GuestMicrophone = GuestMicrophone()
        conversation_request: ConversationRequest = ConversationRequest(voice_key=voice_key)
        expected_validation_problem_count: int = 1
        expected_exception_content: ExpectedExceptionContent = ExpectedExceptionContent(
            message_phrases=[expected_problem_phrase],
            expected_exception_metadata=ExpectedExceptionMetadata(
                http_status_code=BUSINESS_REFUSAL_HTTP_STATUS_CODE,
                exception_action=ExceptionAction.USER_ACTION_REQUIRED,
                reason="The conversation request is not valid",
                severity=Severity.ERROR,
                log_event=LogEventConversation.CONVERSATION_START,
            ),
            contextual_data_by_name={"Conversation.ValidationProblemCount": expected_validation_problem_count},
        )
        expected_provider_session_count: int = 0

        async with (
            RealtimeVoiceServiceScripted() as realtime_voice_service_scripted,
            create_domain_facade(realtime_voice_service_scripted, restaurant_database_path) as domain_facade,
            aclosing(domain_facade.converse(conversation_request, guest_microphone.stream_guest_side_events())) as conversation,
        ):
            with pytest.raises(ConversationRequestValidationException) as raised:
                await anext(conversation)

        AsserterException.assert_validation_refusal_is_as_expected(
            expected_validation_problem_count=expected_validation_problem_count,
            expected_exception_content=expected_exception_content,
            expected_provider_session_count=expected_provider_session_count,
            actual_conversation_request_validation_exception=raised.value,
            actual_captured_realtime_sessions=realtime_voice_service_scripted.captured_realtime_sessions,
        )

    async def test_Converse_WhenTheHostStopsReadingEarly_ThenTheProviderSessionIsClosed(self, restaurant_database_path: Path) -> None:
        guest_microphone: GuestMicrophone = GuestMicrophone()
        conversation_request: ConversationRequest = ConversationRequest(voice_key="openai-ash")
        expected_provider_session_count: int = 1

        async with (
            RealtimeVoiceServiceScripted() as realtime_voice_service_scripted,
            create_domain_facade(realtime_voice_service_scripted, restaurant_database_path) as domain_facade,
            asyncio.timeout(CONVERSATION_TIME_LIMIT_SECONDS),
            aclosing(domain_facade.converse(conversation_request, guest_microphone.stream_guest_side_events())) as conversation,
        ):
            await anext(conversation)

        AsserterConversation.assert_provider_sessions_were_closed_by_the_domain(
            expected_provider_session_count=expected_provider_session_count,
            actual_captured_realtime_sessions=realtime_voice_service_scripted.captured_realtime_sessions,
        )

    async def test_Converse_WhenTheHostStopsReadingDuringTheGreeting_ThenTheGuestAudioIsReleasedBeforeTheConversationIsClosed(
        self, restaurant_database_path: Path
    ) -> None:
        # The greeting's speech arrives while guest audio is being forwarded, so stopping there leaves forwarding mid-wait.
        guest_microphone: GuestMicrophone = GuestMicrophone()
        conversation_request: ConversationRequest = ConversationRequest(voice_key=CEDAR_VOICE_OPTION.voice_key)
        expected_audio_stream_was_released: bool = True
        expected_provider_session_count: int = 1

        async with (
            RealtimeVoiceServiceScripted() as realtime_voice_service_scripted,
            create_domain_facade(realtime_voice_service_scripted, restaurant_database_path) as domain_facade,
            asyncio.timeout(CONVERSATION_TIME_LIMIT_SECONDS),
        ):
            async with aclosing(domain_facade.converse(conversation_request, guest_microphone.stream_guest_side_events())) as conversation:
                await anext(conversation)
                await anext(conversation)
            actual_audio_stream_was_released: bool = guest_microphone.audio_stream_was_released

        assert actual_audio_stream_was_released == expected_audio_stream_was_released, (
            "Closing the conversation must release the guest's audio stream before the close returns, not leave it to be cleaned up later"
        )
        AsserterConversation.assert_provider_sessions_were_closed_by_the_domain(
            expected_provider_session_count=expected_provider_session_count,
            actual_captured_realtime_sessions=realtime_voice_service_scripted.captured_realtime_sessions,
        )

    async def test_Converse_WhenTheGuestAudioFails_ThenTheFailureEndsTheConversationAndTheProviderSessionIsClosed(
        self, restaurant_database_path: Path
    ) -> None:
        guest_microphone: GuestMicrophone = GuestMicrophone()
        conversation_request: ConversationRequest = ConversationRequest(voice_key=CEDAR_VOICE_OPTION.voice_key)
        expected_failure_message: str = "The guest's microphone stopped delivering audio."
        expected_provider_session_count: int = 1

        async with (
            RealtimeVoiceServiceScripted() as realtime_voice_service_scripted,
            create_domain_facade(realtime_voice_service_scripted, restaurant_database_path) as domain_facade,
            aclosing(domain_facade.converse(conversation_request, guest_microphone.stream_guest_side_events())) as conversation,
        ):
            with pytest.raises(GuestMicrophoneBreakdownException, match=expected_failure_message):
                async with asyncio.timeout(CONVERSATION_TIME_LIMIT_SECONDS):
                    await guest_microphone.take_part(
                        conversation,
                        GUEST_AUDIO_CHUNKS[:1],
                        guest_microphone_breakdown_exception=GuestMicrophoneBreakdownException(expected_failure_message),
                    )

        AsserterConversation.assert_provider_sessions_were_closed_by_the_domain(
            expected_provider_session_count=expected_provider_session_count,
            actual_captured_realtime_sessions=realtime_voice_service_scripted.captured_realtime_sessions,
        )


class TestConversationProviderFailures:
    async def test_Converse_WhenTheProviderRefusesTheApiKey_ThenAccessIsDeniedBeforeTheCallStarts(self, restaurant_database_path: Path) -> None:
        guest_microphone: GuestMicrophone = GuestMicrophone()
        conversation_request: ConversationRequest = ConversationRequest(voice_key=CEDAR_VOICE_OPTION.voice_key)
        refusal_status: HTTPStatus = HTTPStatus.UNAUTHORIZED
        expected_exception_content: ExpectedExceptionContent = ExpectedExceptionContent(
            message_phrases=["refused the API key", f"HTTP {refusal_status.value}", TESTING_REALTIME_MODEL],
            expected_exception_metadata=ExpectedExceptionMetadata(
                http_status_code=TECHNICAL_FAILURE_HTTP_STATUS_CODE,
                exception_action=ExceptionAction.INFRA_ACTION_REQUIRED,
                reason=PROVIDER_ACCESS_DENIED_REASON,
                severity=Severity.ERROR,
                log_event=LogEventRealtimeVoice.SESSION_OPEN,
            ),
            contextual_data_by_name={OPERATION_CONTEXT_NAME: CONNECT_OPERATION, "RealtimeVoice.HttpStatusCode": refusal_status.value},
            absent_phrases=[SCRIPTED_SERVICE_API_KEY],
        )
        expected_provider_session_count: int = 0

        async with (
            RealtimeVoiceServiceScripted(handshake_refusal_status=refusal_status) as realtime_voice_service_scripted,
            create_domain_facade(realtime_voice_service_scripted, restaurant_database_path) as domain_facade,
            aclosing(domain_facade.converse(conversation_request, guest_microphone.stream_guest_side_events())) as conversation,
        ):
            with pytest.raises(RealtimeVoiceProviderAccessDeniedException) as raised:
                async with asyncio.timeout(CONVERSATION_TIME_LIMIT_SECONDS):
                    await anext(conversation)

        AsserterException.assert_call_failure_is_as_expected(
            expected_exception_content=expected_exception_content,
            expected_provider_session_count=expected_provider_session_count,
            actual_voice_agent_conversation_exception=raised.value,
            actual_captured_realtime_sessions=realtime_voice_service_scripted.captured_realtime_sessions,
        )

    async def test_Converse_WhenTheProviderClosesTheConnectionForAnInvalidApiKey_ThenAccessIsDeniedBeforeTheCallStarts(
        self, restaurant_database_path: Path
    ) -> None:
        guest_microphone: GuestMicrophone = GuestMicrophone()
        conversation_request: ConversationRequest = ConversationRequest(voice_key=CEDAR_VOICE_OPTION.voice_key)
        refusal_close_reason: str = "invalid_request_error.invalid_api_key"
        expected_exception_content: ExpectedExceptionContent = ExpectedExceptionContent(
            message_phrases=["refused the account while configuring the session", refusal_close_reason],
            expected_exception_metadata=ExpectedExceptionMetadata(
                http_status_code=TECHNICAL_FAILURE_HTTP_STATUS_CODE,
                exception_action=ExceptionAction.INFRA_ACTION_REQUIRED,
                reason=PROVIDER_ACCESS_DENIED_REASON,
                severity=Severity.ERROR,
                log_event=LogEventRealtimeVoice.SESSION_CONFIGURATION,
            ),
            contextual_data_by_name={
                OPERATION_CONTEXT_NAME: "configuring the session",
                PROVIDER_ERROR_TYPE_CONTEXT_NAME: "invalid_request_error",
                PROVIDER_ERROR_CODE_CONTEXT_NAME: "invalid_api_key",
            },
            absent_phrases=[SCRIPTED_SERVICE_API_KEY],
        )
        expected_provider_session_count: int = 0

        async with (
            RealtimeVoiceServiceScripted(connection_refusal_close_reason=refusal_close_reason) as realtime_voice_service_scripted,
            create_domain_facade(realtime_voice_service_scripted, restaurant_database_path) as domain_facade,
            aclosing(domain_facade.converse(conversation_request, guest_microphone.stream_guest_side_events())) as conversation,
        ):
            with pytest.raises(RealtimeVoiceProviderAccessDeniedException) as raised:
                async with asyncio.timeout(CONVERSATION_TIME_LIMIT_SECONDS):
                    await anext(conversation)

        AsserterException.assert_call_failure_is_as_expected(
            expected_exception_content=expected_exception_content,
            expected_provider_session_count=expected_provider_session_count,
            actual_voice_agent_conversation_exception=raised.value,
            actual_captured_realtime_sessions=realtime_voice_service_scripted.captured_realtime_sessions,
        )

    async def test_Converse_WhenTheProviderRejectsTheSessionSettings_ThenAProviderErrorIsRaisedBeforeTheCallStarts(
        self, restaurant_database_path: Path
    ) -> None:
        guest_microphone: GuestMicrophone = GuestMicrophone()
        conversation_request: ConversationRequest = ConversationRequest(voice_key=CEDAR_VOICE_OPTION.voice_key)
        provider_error_type: str = "invalid_request_error"
        provider_error_code: str = "invalid_value"
        provider_error_message: str = "Invalid value: 'cedar'. Supported values are: 'alloy'."
        session_update_error_event_message: ErrorEventMessage = create_error_event(provider_error_type, provider_error_code, provider_error_message)
        configure_operation: str = "configuring the session"
        expected_exception_content: ExpectedExceptionContent = ExpectedExceptionContent(
            message_phrases=[configure_operation, provider_error_message],
            expected_exception_metadata=ExpectedExceptionMetadata(
                http_status_code=PROVIDER_ERROR_HTTP_STATUS_CODE,
                exception_action=ExceptionAction.DEVELOPER_ACTION_REQUIRED,
                reason="The voice service reported an error",
                severity=Severity.ERROR,
                log_event=LogEventRealtimeVoice.SESSION_CONFIGURATION,
            ),
            contextual_data_by_name={
                OPERATION_CONTEXT_NAME: configure_operation,
                PROVIDER_ERROR_TYPE_CONTEXT_NAME: provider_error_type,
                PROVIDER_ERROR_CODE_CONTEXT_NAME: provider_error_code,
            },
        )
        expected_provider_session_count: int = 1

        async with (
            RealtimeVoiceServiceScripted(session_update_error_event_message=session_update_error_event_message) as realtime_voice_service_scripted,
            create_domain_facade(realtime_voice_service_scripted, restaurant_database_path) as domain_facade,
            aclosing(domain_facade.converse(conversation_request, guest_microphone.stream_guest_side_events())) as conversation,
        ):
            with pytest.raises(RealtimeVoiceProviderErrorException) as raised:
                async with asyncio.timeout(CONVERSATION_TIME_LIMIT_SECONDS):
                    await anext(conversation)

        AsserterException.assert_call_failure_is_as_expected(
            expected_exception_content=expected_exception_content,
            expected_provider_session_count=expected_provider_session_count,
            actual_voice_agent_conversation_exception=raised.value,
            actual_captured_realtime_sessions=realtime_voice_service_scripted.captured_realtime_sessions,
        )

    async def test_Converse_WhenTheProviderEndsTheSessionAtItsTimeLimit_ThenTheGuestIsToldToCallAgainAndTheProviderSessionIsClosed(
        self, restaurant_database_path: Path
    ) -> None:
        guest_microphone: GuestMicrophone = GuestMicrophone()
        conversation_request: ConversationRequest = ConversationRequest(voice_key=CEDAR_VOICE_OPTION.voice_key)
        session_expiry: ErrorEventMessage = create_error_event(
            "invalid_request_error", "session_expired", "Your session hit the maximum duration of 60 minutes."
        )
        guest_keeps_listening_event_count: int = 99
        expected_provider_session_count: int = 1
        expected_exception_content: ExpectedExceptionContent = ExpectedExceptionContent(
            message_phrases=["reached the longest a single call can last", "Please call again"],
            expected_exception_metadata=ExpectedExceptionMetadata(
                http_status_code=BUSINESS_REFUSAL_HTTP_STATUS_CODE,
                exception_action=ExceptionAction.USER_ACTION_REQUIRED,
                reason="The call reached its time limit",
                severity=Severity.ERROR,
                log_event=LogEventRealtimeVoice.EVENT_RECEIPT,
            ),
            contextual_data_by_name={
                OPERATION_CONTEXT_NAME: "conversing",
                PROVIDER_ERROR_TYPE_CONTEXT_NAME: session_expiry["error"]["type"],
                PROVIDER_ERROR_CODE_CONTEXT_NAME: "session_expired",
                PROVIDER_ERROR_MESSAGE_CONTEXT_NAME: session_expiry["error"]["message"],
            },
            withheld_message_phrases=[session_expiry["error"]["message"]],
        )

        async with (
            RealtimeVoiceServiceScripted(events_after_each_guest_audio=[session_expiry]) as realtime_voice_service_scripted,
            create_domain_facade(realtime_voice_service_scripted, restaurant_database_path) as domain_facade,
            aclosing(domain_facade.converse(conversation_request, guest_microphone.stream_guest_side_events())) as conversation,
        ):
            with pytest.raises(RealtimeVoiceSessionExpiredException) as raised:
                async with asyncio.timeout(CONVERSATION_TIME_LIMIT_SECONDS):
                    await guest_microphone.take_part(
                        conversation, GUEST_AUDIO_CHUNKS[:1], hang_up_after_event_count=guest_keeps_listening_event_count
                    )

        AsserterException.assert_call_failure_is_as_expected(
            expected_exception_content=expected_exception_content,
            expected_provider_session_count=expected_provider_session_count,
            actual_voice_agent_conversation_exception=raised.value,
            actual_captured_realtime_sessions=realtime_voice_service_scripted.captured_realtime_sessions,
        )

    @pytest.mark.parametrize(
        "provider_failure_scenario",
        [
            pytest.param(
                ProviderFailureScenario(
                    scripted_server_event_message=create_error_event("server_error", None, "The server had an error while processing your request."),
                    expected_exception_type=RealtimeVoiceProviderUnavailableException,
                    expected_exception_content=ExpectedExceptionContent(
                        message_phrases=["failed while conversing", "The server had an error while processing your request."],
                        expected_exception_metadata=ExpectedExceptionMetadata(
                            http_status_code=SERVICE_UNAVAILABLE_HTTP_STATUS_CODE,
                            exception_action=ExceptionAction.RETRY_ACTION_NEEDED,
                            reason=PROVIDER_UNAVAILABLE_REASON,
                            severity=Severity.ERROR,
                            log_event=LogEventRealtimeVoice.EVENT_RECEIPT,
                        ),
                        contextual_data_by_name={OPERATION_CONTEXT_NAME: "conversing", PROVIDER_ERROR_TYPE_CONTEXT_NAME: "server_error"},
                        absent_contextual_data_names=[PROVIDER_ERROR_CODE_CONTEXT_NAME],
                    ),
                ),
                id="server-error-event",
            ),
            pytest.param(
                ProviderFailureScenario(
                    scripted_server_event_message=create_failed_response_event(
                        "insufficient_quota", "insufficient_quota", "You exceeded your current quota."
                    ),
                    expected_exception_type=RealtimeVoiceProviderAccessDeniedException,
                    expected_exception_content=ExpectedExceptionContent(
                        message_phrases=["refused the account while conversing", "You exceeded your current quota."],
                        expected_exception_metadata=ExpectedExceptionMetadata(
                            http_status_code=TECHNICAL_FAILURE_HTTP_STATUS_CODE,
                            exception_action=ExceptionAction.INFRA_ACTION_REQUIRED,
                            reason=PROVIDER_ACCESS_DENIED_REASON,
                            severity=Severity.ERROR,
                            log_event=LogEventRealtimeVoice.EVENT_RECEIPT,
                        ),
                        contextual_data_by_name={
                            OPERATION_CONTEXT_NAME: "conversing",
                            PROVIDER_ERROR_TYPE_CONTEXT_NAME: "insufficient_quota",
                            PROVIDER_ERROR_CODE_CONTEXT_NAME: "insufficient_quota",
                        },
                    ),
                ),
                id="failed-response-out-of-quota",
            ),
            pytest.param(
                ProviderFailureScenario(
                    scripted_server_event_message=create_malformed_agent_speech_event(),
                    expected_exception_type=RealtimeVoiceProviderErrorException,
                    expected_exception_content=ExpectedExceptionContent(
                        message_phrases=["reported an error while conversing", "not valid base64 audio"],
                        expected_exception_metadata=ExpectedExceptionMetadata(
                            http_status_code=PROVIDER_ERROR_HTTP_STATUS_CODE,
                            exception_action=ExceptionAction.DEVELOPER_ACTION_REQUIRED,
                            reason="The voice service reported an error",
                            severity=Severity.ERROR,
                            log_event=LogEventRealtimeVoice.EVENT_RECEIPT,
                        ),
                        contextual_data_by_name={OPERATION_CONTEXT_NAME: "conversing", PROVIDER_ERROR_TYPE_CONTEXT_NAME: "malformed_audio"},
                        absent_contextual_data_names=[PROVIDER_ERROR_CODE_CONTEXT_NAME],
                    ),
                ),
                id="malformed-agent-speech",
            ),
        ],
    )
    async def test_Converse_WhenTheProviderReportsAFailureMidConversation_ThenTheFailureIsClassifiedAndTheProviderSessionIsClosed(
        self, restaurant_database_path: Path, provider_failure_scenario: ProviderFailureScenario
    ) -> None:
        guest_microphone: GuestMicrophone = GuestMicrophone()
        conversation_request: ConversationRequest = ConversationRequest(voice_key=CEDAR_VOICE_OPTION.voice_key)
        guest_keeps_listening_event_count: int = 99
        expected_provider_session_count: int = 1

        async with (
            RealtimeVoiceServiceScripted(
                events_after_each_guest_audio=[provider_failure_scenario.scripted_server_event_message]
            ) as realtime_voice_service_scripted,
            create_domain_facade(realtime_voice_service_scripted, restaurant_database_path) as domain_facade,
            aclosing(domain_facade.converse(conversation_request, guest_microphone.stream_guest_side_events())) as conversation,
        ):
            with pytest.raises(provider_failure_scenario.expected_exception_type) as raised:
                async with asyncio.timeout(CONVERSATION_TIME_LIMIT_SECONDS):
                    await guest_microphone.take_part(
                        conversation, GUEST_AUDIO_CHUNKS[:1], hang_up_after_event_count=guest_keeps_listening_event_count
                    )

        AsserterException.assert_call_failure_is_as_expected(
            expected_exception_content=provider_failure_scenario.expected_exception_content,
            expected_provider_session_count=expected_provider_session_count,
            actual_voice_agent_conversation_exception=raised.value,
            actual_captured_realtime_sessions=realtime_voice_service_scripted.captured_realtime_sessions,
        )


class TestVoiceOptions:
    async def test_GetVoiceOptions_WhenAsked_ThenEveryCatalogVoiceIsListedWithFemaleAndMaleChoicesInCatalogOrder(
        self, restaurant_database_path: Path
    ) -> None:
        expected_voice_options: list[VoiceOption] = read_catalog_voice_options()
        assert {voice_option.presented_gender for voice_option in expected_voice_options} == set(PresentedGender), (
            "The bundled catalog must offer both female and male voices for this scenario"
        )

        async with (
            RealtimeVoiceServiceScripted() as realtime_voice_service_scripted,
            create_domain_facade(realtime_voice_service_scripted, restaurant_database_path) as domain_facade,
        ):
            actual_voice_options: list[VoiceOption] = await domain_facade.get_voice_options()

        assert actual_voice_options == expected_voice_options


class TestClose:
    async def test_Close_WhenTheHostHasStopped_ThenALaterConversationNeverReachesTheSpeechProvider(self, restaurant_database_path: Path) -> None:
        guest_microphone: GuestMicrophone = GuestMicrophone()
        conversation_request: ConversationRequest = ConversationRequest(voice_key=CEDAR_VOICE_OPTION.voice_key)
        expected_exception_content: ExpectedExceptionContent = ExpectedExceptionContent(
            message_phrases=["the gateway is already closed"],
            expected_exception_metadata=ExpectedExceptionMetadata(
                http_status_code=SERVICE_UNAVAILABLE_HTTP_STATUS_CODE,
                exception_action=ExceptionAction.RETRY_ACTION_NEEDED,
                reason=PROVIDER_UNAVAILABLE_REASON,
                severity=Severity.ERROR,
                log_event=LogEventRealtimeVoice.SESSION_OPEN,
            ),
            contextual_data_by_name={OPERATION_CONTEXT_NAME: CONNECT_OPERATION},
        )
        expected_provider_session_count: int = 0

        async with RealtimeVoiceServiceScripted() as realtime_voice_service_scripted:
            domain_facade: DomainFacade = create_domain_facade(realtime_voice_service_scripted, restaurant_database_path)
            await domain_facade.close()
            async with aclosing(domain_facade.converse(conversation_request, guest_microphone.stream_guest_side_events())) as conversation:
                with pytest.raises(RealtimeVoiceProviderUnavailableException) as raised:
                    await anext(conversation)

        AsserterException.assert_call_failure_is_as_expected(
            expected_exception_content=expected_exception_content,
            expected_provider_session_count=expected_provider_session_count,
            actual_voice_agent_conversation_exception=raised.value,
            actual_captured_realtime_sessions=realtime_voice_service_scripted.captured_realtime_sessions,
        )
