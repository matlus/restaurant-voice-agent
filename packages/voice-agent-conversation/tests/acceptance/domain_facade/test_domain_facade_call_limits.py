# Acceptance tests for the limits on a call, black-box through the conversation DomainFacade. Every call holds a paid
# speech provider session, so a call ends with a spoken goodbye at its time or silence limit, and guest speech that is
# too large or arrives faster than it could be spoken never reaches the provider. The
# scripted Realtime service answers every reply request with the same speech, so the farewell sounds like the greeting;
# what tells them apart is the instructions the farewell request carried.

import asyncio
import secrets
from contextlib import aclosing
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pytest
from conversation_acceptance_support.asserters.asserter_conversation import AsserterConversation
from conversation_acceptance_support.asserters.asserter_exception import AsserterException, ExpectedExceptionContent, ExpectedExceptionMetadata
from conversation_acceptance_support.bundled_voice_catalog import read_catalog_voice_option
from conversation_acceptance_support.guest_microphone import GREETING_EVENT_COUNT, GuestMicrophone
from conversation_acceptance_support.realtime_voice_service_scripted import (
    ACTIVE_RESPONSE_ERROR_CODE,
    SCRIPTED_GREETING_AUDIO,
    RealtimeVoiceServiceScripted,
)
from conversation_acceptance_support.service_locator_testing import (
    MAXIMUM_CALL_SECONDS_VARIABLE_NAME,
    MAXIMUM_SILENCE_SECONDS_VARIABLE_NAME,
    ServiceLocatorTesting,
    create_domain_facade,
    create_service_locator_testing,
)

from voice_agent_conversation import (
    AgentSpeechChunk,
    AgentTurnFinished,
    CallLimit,
    CallLimitReached,
    ConfigurationSettingException,
    ConversationAudioFormat,
    ConversationEvent,
    ConversationRequest,
    ConversationStarted,
    DomainFacade,
    ExceptionAction,
    LogEventConfiguration,
    Severity,
    SpeechProviderErrorTolerated,
    VoiceOption,
)

CEDAR_VOICE_OPTION: Final[VoiceOption] = read_catalog_voice_option("openai-cedar")
CONVERSATION_REQUEST: Final[ConversationRequest] = ConversationRequest(voice_key=CEDAR_VOICE_OPTION.voice_key)
PROVIDER_CONVERSATION_AUDIO_FORMAT: Final[ConversationAudioFormat] = ConversationAudioFormat(
    guest_audio_sample_rate_hz=24_000, agent_audio_sample_rate_hz=24_000
)
GREETING_EVENTS: Final[list[ConversationEvent]] = [
    ConversationStarted(conversation_audio_format=PROVIDER_CONVERSATION_AUDIO_FORMAT, voice_option=CEDAR_VOICE_OPTION),
    AgentSpeechChunk(pcm_audio=SCRIPTED_GREETING_AUDIO),
    AgentTurnFinished(),
]
FAREWELL_EVENTS: Final[list[ConversationEvent]] = [AgentSpeechChunk(pcm_audio=SCRIPTED_GREETING_AUDIO), AgentTurnFinished()]
# Short enough that a limit is reached well within the conversation time limit, long enough to follow the greeting.
SHORT_LIMIT_SECONDS: Final[str] = "0.3"
FAREWELL_INSTRUCTION_PHRASE: Final[str] = "tell the caller the call is ending"
CONVERSATION_TIME_LIMIT_SECONDS: Final[float] = 5.0
# The guest is silent; the call ends by itself long before the guest would hang up.
GUEST_KEEPS_LISTENING_EVENT_COUNT: Final[int] = 99
# One second of mono 16-bit PCM at the provider's rate is the most guest speech the provider takes at once, and the
# largest piece it takes is a fifth of that.
BURST_BYTE_COUNT: Final[int] = PROVIDER_CONVERSATION_AUDIO_FORMAT.guest_audio_sample_rate_hz * 2
LARGEST_PIECE_BYTE_COUNT: Final[int] = BURST_BYTE_COUNT // 5
TECHNICAL_FAILURE_HTTP_STATUS_CODE: Final[int] = 500
SETTING_VALUE_CONTEXT_NAME: Final[str] = "Configuration.SettingValue"


@dataclass(frozen=True)
class FarewellRequest:
    reply_request_count: int
    last_reply_carried_farewell_instructions: bool


def read_farewell_request(realtime_voice_service_scripted: RealtimeVoiceServiceScripted) -> FarewellRequest:
    agent_response_instructions: list[str | None] = realtime_voice_service_scripted.captured_realtime_sessions[0].agent_response_instructions
    last_reply_instructions: str | None = agent_response_instructions[-1]
    return FarewellRequest(
        reply_request_count=len(agent_response_instructions),
        last_reply_carried_farewell_instructions=last_reply_instructions is not None and FAREWELL_INSTRUCTION_PHRASE in last_reply_instructions,
    )


class TestCallLimits:
    @pytest.mark.parametrize(
        ("limit_variable_name", "expected_call_limit"),
        [
            pytest.param(MAXIMUM_CALL_SECONDS_VARIABLE_NAME, CallLimit.MAXIMUM_DURATION, id="maximum-duration"),
            pytest.param(MAXIMUM_SILENCE_SECONDS_VARIABLE_NAME, CallLimit.MAXIMUM_SILENCE, id="maximum-silence"),
        ],
    )
    async def test_Converse_WhenTheCallReachesALimit_ThenTheAgentSaysGoodbyeAndTheCallEndsNamingTheLimit(
        self, restaurant_database_path: Path, limit_variable_name: str, expected_call_limit: CallLimit
    ) -> None:
        guest_microphone: GuestMicrophone = GuestMicrophone()
        expected_conversation_events: list[ConversationEvent] = [*GREETING_EVENTS, *FAREWELL_EVENTS, CallLimitReached(call_limit=expected_call_limit)]
        expected_farewell_request: FarewellRequest = FarewellRequest(reply_request_count=2, last_reply_carried_farewell_instructions=True)

        async with (
            RealtimeVoiceServiceScripted() as realtime_voice_service_scripted,
            create_domain_facade(
                realtime_voice_service_scripted, restaurant_database_path, {limit_variable_name: SHORT_LIMIT_SECONDS}
            ) as domain_facade,
            asyncio.timeout(CONVERSATION_TIME_LIMIT_SECONDS),
            aclosing(domain_facade.converse(CONVERSATION_REQUEST, guest_microphone.stream_guest_side_events())) as conversation,
        ):
            actual_conversation_events: list[ConversationEvent] = await guest_microphone.take_part(
                conversation, [], hang_up_after_event_count=GUEST_KEEPS_LISTENING_EVENT_COUNT
            )

        AsserterConversation.assert_conversation_events_are_as_expected(
            expected_conversation_events=expected_conversation_events, actual_conversation_events=actual_conversation_events
        )
        assert read_farewell_request(realtime_voice_service_scripted) == expected_farewell_request

    async def test_Converse_WhenTheProviderRefusesTheFarewellBecauseAReplyIsUnderWay_ThenTheFarewellIsAskedForAgainOnceThatReplyEnds(
        self, restaurant_database_path: Path
    ) -> None:
        guest_microphone: GuestMicrophone = GuestMicrophone()
        farewell_request_number: int = 2
        expected_conversation_events: list[ConversationEvent] = [
            *GREETING_EVENTS,
            SpeechProviderErrorTolerated(
                error_type="invalid_request_error",
                error_code=ACTIVE_RESPONSE_ERROR_CODE,
                error_message="Conversation already has an active response in progress.",
            ),
            AgentTurnFinished(),
            *FAREWELL_EVENTS,
            CallLimitReached(call_limit=CallLimit.MAXIMUM_DURATION),
        ]
        expected_farewell_request: FarewellRequest = FarewellRequest(reply_request_count=3, last_reply_carried_farewell_instructions=True)

        async with (
            RealtimeVoiceServiceScripted(refused_reply_request_numbers=[farewell_request_number]) as realtime_voice_service_scripted,
            create_domain_facade(
                realtime_voice_service_scripted, restaurant_database_path, {MAXIMUM_CALL_SECONDS_VARIABLE_NAME: SHORT_LIMIT_SECONDS}
            ) as domain_facade,
            asyncio.timeout(CONVERSATION_TIME_LIMIT_SECONDS),
            aclosing(domain_facade.converse(CONVERSATION_REQUEST, guest_microphone.stream_guest_side_events())) as conversation,
        ):
            actual_conversation_events: list[ConversationEvent] = await guest_microphone.take_part(
                conversation, [], hang_up_after_event_count=GUEST_KEEPS_LISTENING_EVENT_COUNT
            )

        AsserterConversation.assert_conversation_events_are_as_expected(
            expected_conversation_events=expected_conversation_events, actual_conversation_events=actual_conversation_events
        )
        assert read_farewell_request(realtime_voice_service_scripted) == expected_farewell_request

    async def test_Converse_WhenTheGuestSendsAnOversizedPieceThenSpeechFasterThanRealTime_ThenOnlySpeechWithinTheAllowanceReachesTheProvider(
        self, restaurant_database_path: Path
    ) -> None:
        guest_microphone: GuestMicrophone = GuestMicrophone()
        burst_piece_count: int = BURST_BYTE_COUNT // LARGEST_PIECE_BYTE_COUNT
        oversized_piece: bytes = secrets.token_bytes(LARGEST_PIECE_BYTE_COUNT + 2)
        largest_pieces: list[bytes] = [secrets.token_bytes(LARGEST_PIECE_BYTE_COUNT) for _ in range(burst_piece_count + 2)]
        expected_guest_audio: list[bytes] = largest_pieces[:burst_piece_count]

        async with (
            RealtimeVoiceServiceScripted() as realtime_voice_service_scripted,
            create_domain_facade(realtime_voice_service_scripted, restaurant_database_path) as domain_facade,
            asyncio.timeout(CONVERSATION_TIME_LIMIT_SECONDS),
            aclosing(domain_facade.converse(CONVERSATION_REQUEST, guest_microphone.stream_guest_side_events())) as conversation,
        ):
            await guest_microphone.take_part(conversation, [oversized_piece, *largest_pieces], hang_up_after_event_count=GREETING_EVENT_COUNT)

        actual_guest_audio: list[bytes] = realtime_voice_service_scripted.captured_realtime_sessions[0].guest_audio
        assert actual_guest_audio == expected_guest_audio


class TestCallLimitSettings:
    @pytest.mark.parametrize(
        ("maximum_call_seconds", "expected_message_phrase"),
        [
            pytest.param("soon", "'soon'", id="not-a-number"),
            pytest.param("0", "'0'", id="zero"),
            pytest.param("nan", "'nan'", id="not-a-number-value"),
            pytest.param("inf", "'inf'", id="infinite"),
        ],
    )
    def test_Construct_WhenAMaximumCallLengthIsNotAPositiveFiniteNumber_ThenTheHostCannotStartAndIsToldWhichSettingToFix(
        self, restaurant_database_path: Path, maximum_call_seconds: str, expected_message_phrase: str
    ) -> None:
        realtime_voice_service_scripted: RealtimeVoiceServiceScripted = RealtimeVoiceServiceScripted()
        expected_exception_content: ExpectedExceptionContent = ExpectedExceptionContent(
            message_phrases=[MAXIMUM_CALL_SECONDS_VARIABLE_NAME, "greater than zero", expected_message_phrase],
            expected_exception_metadata=ExpectedExceptionMetadata(
                http_status_code=TECHNICAL_FAILURE_HTTP_STATUS_CODE,
                exception_action=ExceptionAction.INFRA_ACTION_REQUIRED,
                reason="Configuration settings are not set up correctly",
                severity=Severity.ERROR,
                log_event=LogEventConfiguration.CALL_LIMIT_SETTINGS_RETRIEVAL,
            ),
            contextual_data_by_name={
                "Configuration.EnvironmentVariableName": MAXIMUM_CALL_SECONDS_VARIABLE_NAME,
                SETTING_VALUE_CONTEXT_NAME: maximum_call_seconds,
            },
        )
        expected_provider_session_count: int = 0

        with realtime_voice_service_scripted:
            service_locator_testing: ServiceLocatorTesting = create_service_locator_testing(
                realtime_voice_service_scripted, restaurant_database_path, {MAXIMUM_CALL_SECONDS_VARIABLE_NAME: maximum_call_seconds}
            )
            with pytest.raises(ConfigurationSettingException) as raised:
                DomainFacade(service_locator_testing)

        AsserterException.assert_call_failure_is_as_expected(
            expected_exception_content=expected_exception_content,
            expected_provider_session_count=expected_provider_session_count,
            actual_voice_agent_conversation_exception=raised.value,
            actual_captured_realtime_sessions=realtime_voice_service_scripted.captured_realtime_sessions,
        )
