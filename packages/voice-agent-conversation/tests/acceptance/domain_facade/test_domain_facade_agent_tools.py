# Acceptance tests for the tools the agent calls during a conversation, black-box through the conversation DomainFacade.
# The scripted Realtime service plays the speech model: once the guest speaks, it calls a tool and ends that reply
# without speech. The tool runs against the real restaurant store, and the service captures the answer sent back.
# Every expected answer is read from the restaurant itself before the call.

import asyncio
import json
from contextlib import aclosing
from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import pytest
from conversation_acceptance_support.asserters.asserter_conversation import AsserterConversation
from conversation_acceptance_support.asserters.asserter_exception import AsserterException, ExpectedExceptionContent, ExpectedExceptionMetadata
from conversation_acceptance_support.bundled_voice_catalog import read_catalog_voice_option
from conversation_acceptance_support.guest_microphone import GuestMicrophone
from conversation_acceptance_support.realtime_voice_service_scripted import (
    SCRIPTED_GREETING_AUDIO,
    CapturedRealtimeSession,
    CapturedToolOutput,
    RealtimeVoiceServiceScripted,
    create_tool_call_events,
)
from conversation_acceptance_support.service_locator_testing import create_domain_facade, create_restaurant_domain_facade

from voice_agent_conversation import (
    AgentSpeechChunk,
    AgentToolCallRepairsExhaustedException,
    AgentTurnFinished,
    ConversationAudioFormat,
    ConversationEvent,
    ConversationRequest,
    ConversationStarted,
    ExceptionAction,
    LogEventAgentTool,
    Severity,
    VoiceOption,
)
from voice_agent_restaurant import (
    AvailabilityRequest,
    ClosedWeekday,
    Dish,
    MenuSearchRequest,
    OpeningHours,
    ReservationPolicyRefusedException,
    RestaurantClosedOnDateException,
    Weekday,
)

CEDAR_VOICE_OPTION: Final[VoiceOption] = read_catalog_voice_option("openai-cedar")
CONVERSATION_REQUEST: Final[ConversationRequest] = ConversationRequest(voice_key=CEDAR_VOICE_OPTION.voice_key)
PROVIDER_AUDIO_FORMAT: Final[ConversationAudioFormat] = ConversationAudioFormat(guest_audio_sample_rate_hz=24_000, agent_audio_sample_rate_hz=24_000)
GUEST_QUESTION_AUDIO: Final[bytes] = b"guest asks the agent something"
CONVERSATION_TIME_LIMIT_SECONDS: Final[float] = 5.0
TOOL_CALL_ID: Final[str] = "call_guest_question"
SECOND_TOOL_CALL_ID: Final[str] = "call_guest_question_again"
UNKNOWN_TOOL_NAME: Final[str] = "order_pizza"
KETO_SEARCH_ARGUMENTS_JSON: Final[str] = '{"diet_labels": ["keto"]}'
WRONG_CALLS_ALLOWED_IN_A_ROW: Final[int] = 3
TECHNICAL_FAILURE_HTTP_STATUS_CODE: Final[int] = 500
GREETING_EVENTS: Final[list[ConversationEvent]] = [
    ConversationStarted(audio_format=PROVIDER_AUDIO_FORMAT, voice_option=CEDAR_VOICE_OPTION),
    AgentSpeechChunk(pcm_audio=SCRIPTED_GREETING_AUDIO),
    AgentTurnFinished(),
]
# The reply the agent gives once its tool call is answered.
ANSWER_EVENTS: Final[list[ConversationEvent]] = [AgentSpeechChunk(pcm_audio=SCRIPTED_GREETING_AUDIO), AgentTurnFinished()]
EXPECTED_CONVERSATION_EVENTS: Final[list[ConversationEvent]] = GREETING_EVENTS + ANSWER_EVENTS
RESTAURANT_TOOL_NAMES: Final[tuple[str, ...]] = (
    "search_menu",
    "describe_dish",
    "get_opening_hours",
    "check_availability",
    "book_table",
    "find_bookings",
    "change_booking",
    "cancel_booking",
)


def count_events_after_answers(answer_count: int) -> int:
    """How many conversation events have arrived once the greeting and the given number of answered tool calls are over."""
    return len(GREETING_EVENTS) + len(ANSWER_EVENTS) * answer_count


def collect_tool_outputs(realtime_voice_service_scripted: RealtimeVoiceServiceScripted) -> list[CapturedToolOutput]:
    return [
        captured_tool_output
        for captured_realtime_session in realtime_voice_service_scripted.captured_realtime_sessions
        for captured_tool_output in captured_realtime_session.tool_outputs
    ]


def count_agent_response_requests(realtime_voice_service_scripted: RealtimeVoiceServiceScripted) -> int:
    return sum(
        captured_realtime_session.agent_response_request_count
        for captured_realtime_session in realtime_voice_service_scripted.captured_realtime_sessions
    )


async def create_tomorrows_availability_request(restaurant_database_path: Path, reservation_time: str, party_size: int) -> AvailabilityRequest:
    async with create_restaurant_domain_facade(restaurant_database_path) as restaurant_domain_facade:
        restaurant_local_now: datetime = await restaurant_domain_facade.get_restaurant_local_now()
    tomorrow: date = restaurant_local_now.date() + timedelta(days=1)
    return AvailabilityRequest(reservation_date=tomorrow.isoformat(), reservation_time=reservation_time, party_size=party_size)


async def read_policy_refusal(restaurant_database_path: Path, availability_request: AvailabilityRequest) -> str:
    """What the restaurant itself says when its booking policy does not allow the availability request."""
    async with create_restaurant_domain_facade(restaurant_database_path) as restaurant_domain_facade:
        with pytest.raises(ReservationPolicyRefusedException) as raised:
            await restaurant_domain_facade.check_availability(availability_request)
    return raised.value.message


def derive_next_closed_date(restaurant_local_now: datetime, opening_hours: OpeningHours) -> date:
    closed_weekdays: list[Weekday] = [
        weekday_hours.weekday for weekday_hours in opening_hours.weekly_hours if isinstance(weekday_hours, ClosedWeekday)
    ]
    assert closed_weekdays, "The restaurant must close on some weekday for this scenario; the seeded data no longer supports it"
    days_ahead: int = 1
    while list(Weekday)[(restaurant_local_now.date() + timedelta(days=days_ahead)).weekday()] not in closed_weekdays:
        days_ahead += 1
    return restaurant_local_now.date() + timedelta(days=days_ahead)


class TestAgentTools:
    async def test_Converse_WhenAConversationStarts_ThenTheAgentIsGivenEveryRestaurantTool(self, restaurant_database_path: Path) -> None:
        guest_microphone: GuestMicrophone = GuestMicrophone()
        expected_tool_names: list[tuple[str, ...]] = [RESTAURANT_TOOL_NAMES]

        async with (
            RealtimeVoiceServiceScripted() as realtime_voice_service_scripted,
            create_domain_facade(realtime_voice_service_scripted, restaurant_database_path) as domain_facade,
            asyncio.timeout(CONVERSATION_TIME_LIMIT_SECONDS),
            aclosing(domain_facade.converse(CONVERSATION_REQUEST, guest_microphone.stream_audio())) as conversation,
        ):
            await guest_microphone.take_part(conversation, [])

        actual_tool_names: list[tuple[str, ...]] = [
            captured_session_settings.tool_names
            for captured_realtime_session in realtime_voice_service_scripted.captured_realtime_sessions
            for captured_session_settings in captured_realtime_session.session_settings
        ]
        assert actual_tool_names == expected_tool_names

    async def test_Converse_WhenTheAgentSearchesTheMenu_ThenTheRestaurantMenuAnswersAndTheAgentIsAskedToGoOn(
        self, restaurant_database_path: Path
    ) -> None:
        guest_microphone: GuestMicrophone = GuestMicrophone()
        async with create_restaurant_domain_facade(restaurant_database_path) as restaurant_domain_facade:
            keto_dishes: list[Dish] = (
                await restaurant_domain_facade.search_menu(
                    MenuSearchRequest(diet_labels=["keto"], excluded_allergens=[], category=None, maximum_calories=None, search_text=None)
                )
            ).dishes
        assert keto_dishes, "The menu must hold keto dishes for this scenario; the seeded data no longer supports it"
        # Keto is a lifestyle diet, not an allergy question, so the answer carries no allergen notice.
        expected_tool_answer: tuple[list[str], list[str], list[bool]] = (
            [TOOL_CALL_ID],
            [keto_dish.dish_id for keto_dish in keto_dishes],
            [False],
        )
        expected_agent_response_request_count: int = 2

        async with (
            RealtimeVoiceServiceScripted(
                events_after_each_guest_audio=create_tool_call_events(TOOL_CALL_ID, "search_menu", KETO_SEARCH_ARGUMENTS_JSON)
            ) as realtime_voice_service_scripted,
            create_domain_facade(realtime_voice_service_scripted, restaurant_database_path) as domain_facade,
            asyncio.timeout(CONVERSATION_TIME_LIMIT_SECONDS),
            aclosing(domain_facade.converse(CONVERSATION_REQUEST, guest_microphone.stream_audio())) as conversation,
        ):
            actual_conversation_events: list[ConversationEvent] = await guest_microphone.take_part(
                conversation, [GUEST_QUESTION_AUDIO], hang_up_after_event_count=count_events_after_answers(1)
            )

        actual_tool_outputs: list[CapturedToolOutput] = collect_tool_outputs(realtime_voice_service_scripted)
        actual_tool_answers: list[dict[str, Any]] = [json.loads(actual_tool_output.output) for actual_tool_output in actual_tool_outputs]
        actual_tool_answer: tuple[list[str], list[str], list[bool]] = (
            [actual_tool_output.call_id for actual_tool_output in actual_tool_outputs],
            [answered_dish["dish_id"] for actual_tool_answer in actual_tool_answers for answered_dish in actual_tool_answer["dishes"]],
            ["allergen_notice" in actual_tool_answer for actual_tool_answer in actual_tool_answers],
        )
        AsserterConversation.assert_conversation_events_are_as_expected(
            expected_conversation_events=EXPECTED_CONVERSATION_EVENTS, actual_conversation_events=actual_conversation_events
        )
        assert (actual_tool_answer, count_agent_response_requests(realtime_voice_service_scripted)) == (
            expected_tool_answer,
            expected_agent_response_request_count,
        )

    @pytest.mark.parametrize(
        ("tool_name", "arguments_json"),
        [
            pytest.param("search_menu", '{"excluded_allergens": ["tree_nuts"]}', id="menu-search-excluding-an-allergen"),
            pytest.param("search_menu", '{"diet_labels": ["nut_free"]}', id="menu-search-for-a-free-from-diet"),
        ],
    )
    async def test_Converse_WhenTheAgentSearchesTheMenuAboutAnAllergy_ThenTheAnswerCarriesTheRestaurantsAllergenNotice(
        self, restaurant_database_path: Path, tool_name: str, arguments_json: str
    ) -> None:
        guest_microphone: GuestMicrophone = GuestMicrophone()
        async with create_restaurant_domain_facade(restaurant_database_path) as restaurant_domain_facade:
            expected_allergen_notices: list[str] = [(await restaurant_domain_facade.get_restaurant_profile()).allergen_notice]

        async with (
            RealtimeVoiceServiceScripted(
                events_after_each_guest_audio=create_tool_call_events(TOOL_CALL_ID, tool_name, arguments_json)
            ) as realtime_voice_service_scripted,
            create_domain_facade(realtime_voice_service_scripted, restaurant_database_path) as domain_facade,
            asyncio.timeout(CONVERSATION_TIME_LIMIT_SECONDS),
            aclosing(domain_facade.converse(CONVERSATION_REQUEST, guest_microphone.stream_audio())) as conversation,
        ):
            await guest_microphone.take_part(conversation, [GUEST_QUESTION_AUDIO], hang_up_after_event_count=count_events_after_answers(1))

        actual_allergen_notices: list[str] = [
            json.loads(actual_tool_output.output)["allergen_notice"] for actual_tool_output in collect_tool_outputs(realtime_voice_service_scripted)
        ]
        assert actual_allergen_notices == expected_allergen_notices

    async def test_Converse_WhenTheAgentDescribesADish_ThenTheAnswerCarriesTheDishAndTheRestaurantsAllergenNotice(
        self, restaurant_database_path: Path
    ) -> None:
        guest_microphone: GuestMicrophone = GuestMicrophone()
        async with create_restaurant_domain_facade(restaurant_database_path) as restaurant_domain_facade:
            described_dish: Dish = (
                await restaurant_domain_facade.search_menu(
                    MenuSearchRequest(diet_labels=[], excluded_allergens=[], category=None, maximum_calories=None, search_text=None)
                )
            ).dishes[0]
            expected_dish_answers: list[tuple[str, str]] = [
                (described_dish.dish_id, (await restaurant_domain_facade.get_restaurant_profile()).allergen_notice)
            ]

        async with (
            RealtimeVoiceServiceScripted(
                events_after_each_guest_audio=create_tool_call_events(TOOL_CALL_ID, "describe_dish", json.dumps({"dish_name": described_dish.name}))
            ) as realtime_voice_service_scripted,
            create_domain_facade(realtime_voice_service_scripted, restaurant_database_path) as domain_facade,
            asyncio.timeout(CONVERSATION_TIME_LIMIT_SECONDS),
            aclosing(domain_facade.converse(CONVERSATION_REQUEST, guest_microphone.stream_audio())) as conversation,
        ):
            await guest_microphone.take_part(conversation, [GUEST_QUESTION_AUDIO], hang_up_after_event_count=count_events_after_answers(1))

        actual_dish_answers: list[tuple[str, str]] = [
            (dish_answer["dish"]["dish_id"], dish_answer["allergen_notice"])
            for dish_answer in (json.loads(actual_tool_output.output) for actual_tool_output in collect_tool_outputs(realtime_voice_service_scripted))
        ]
        assert actual_dish_answers == expected_dish_answers

    async def test_Converse_WhenTheAgentGoesOnAfterALookup_ThenOnlyItsFirstReplyWasToldToGreet(self, restaurant_database_path: Path) -> None:
        # The greeting instruction once lived in the standing instructions the model reads before every reply, and the
        # model greeted again when asked to go on after a lookup. Now only the first reply request carries it.
        guest_microphone: GuestMicrophone = GuestMicrophone()
        greeting_marker: str = "Greet the caller"
        expected_greeting_placement: tuple[list[bool], bool] = ([True, False], False)

        async with (
            RealtimeVoiceServiceScripted(
                events_after_each_guest_audio=create_tool_call_events(TOOL_CALL_ID, "search_menu", KETO_SEARCH_ARGUMENTS_JSON)
            ) as realtime_voice_service_scripted,
            create_domain_facade(realtime_voice_service_scripted, restaurant_database_path) as domain_facade,
            asyncio.timeout(CONVERSATION_TIME_LIMIT_SECONDS),
            aclosing(domain_facade.converse(CONVERSATION_REQUEST, guest_microphone.stream_audio())) as conversation,
        ):
            await guest_microphone.take_part(conversation, [GUEST_QUESTION_AUDIO], hang_up_after_event_count=count_events_after_answers(1))

        captured_realtime_session: CapturedRealtimeSession = realtime_voice_service_scripted.captured_realtime_sessions[0]
        actual_greeting_placement: tuple[list[bool], bool] = (
            [
                reply_instructions is not None and greeting_marker in reply_instructions
                for reply_instructions in captured_realtime_session.agent_response_instructions
            ],
            any(greeting_marker in session_settings.agent_instructions for session_settings in captured_realtime_session.session_settings),
        )
        assert actual_greeting_placement == expected_greeting_placement

    async def test_Converse_WhenTheRestaurantRefusesTheAgentsRequest_ThenTheAgentIsToldWhyAndTheCallGoesOn(
        self, restaurant_database_path: Path
    ) -> None:
        guest_microphone: GuestMicrophone = GuestMicrophone()
        async with create_restaurant_domain_facade(restaurant_database_path) as restaurant_domain_facade:
            restaurant_local_now: datetime = await restaurant_domain_facade.get_restaurant_local_now()
            closed_date: date = derive_next_closed_date(restaurant_local_now, await restaurant_domain_facade.get_opening_hours())
            availability_request: AvailabilityRequest = AvailabilityRequest(
                reservation_date=closed_date.isoformat(), reservation_time="19:00", party_size=2
            )
            with pytest.raises(RestaurantClosedOnDateException) as raised:
                await restaurant_domain_facade.check_availability(availability_request)
        expected_tool_answers: list[dict[str, object]] = [{"refused": True, "reason": raised.value.message}]

        async with (
            RealtimeVoiceServiceScripted(
                events_after_each_guest_audio=create_tool_call_events(TOOL_CALL_ID, "check_availability", json.dumps(asdict(availability_request)))
            ) as realtime_voice_service_scripted,
            create_domain_facade(realtime_voice_service_scripted, restaurant_database_path) as domain_facade,
            asyncio.timeout(CONVERSATION_TIME_LIMIT_SECONDS),
            aclosing(domain_facade.converse(CONVERSATION_REQUEST, guest_microphone.stream_audio())) as conversation,
        ):
            actual_conversation_events: list[ConversationEvent] = await guest_microphone.take_part(
                conversation, [GUEST_QUESTION_AUDIO], hang_up_after_event_count=count_events_after_answers(1)
            )

        actual_tool_answers: list[dict[str, object]] = [
            json.loads(actual_tool_output.output) for actual_tool_output in collect_tool_outputs(realtime_voice_service_scripted)
        ]
        AsserterConversation.assert_conversation_events_are_as_expected(
            expected_conversation_events=EXPECTED_CONVERSATION_EVENTS, actual_conversation_events=actual_conversation_events
        )
        assert actual_tool_answers == expected_tool_answers

    @pytest.mark.parametrize(
        ("tool_name", "arguments_json", "expected_problem_phrase"),
        [
            pytest.param("check_availability", '{"party_size": "lots"}', "check_availability", id="arguments-that-do-not-fit"),
            pytest.param(UNKNOWN_TOOL_NAME, "{}", f"no tool named '{UNKNOWN_TOOL_NAME}'", id="unknown-tool"),
            pytest.param(
                "check_availability",
                '{"reservation_date": "2026-11-06", "reservation_time": "half past six", "party_size": 2}',
                "is not a time",
                id="time-the-restaurant-cannot-read",
            ),
        ],
    )
    async def test_Converse_WhenTheAgentCallsAToolWrongly_ThenItIsToldHowToCallAgainAndTheCallGoesOn(
        self, restaurant_database_path: Path, tool_name: str, arguments_json: str, expected_problem_phrase: str
    ) -> None:
        guest_microphone: GuestMicrophone = GuestMicrophone()
        expected_call_rejections: list[tuple[bool, bool]] = [(True, True)]

        async with (
            RealtimeVoiceServiceScripted(
                events_after_each_guest_audio=create_tool_call_events(TOOL_CALL_ID, tool_name, arguments_json)
            ) as realtime_voice_service_scripted,
            create_domain_facade(realtime_voice_service_scripted, restaurant_database_path) as domain_facade,
            asyncio.timeout(CONVERSATION_TIME_LIMIT_SECONDS),
            aclosing(domain_facade.converse(CONVERSATION_REQUEST, guest_microphone.stream_audio())) as conversation,
        ):
            actual_conversation_events: list[ConversationEvent] = await guest_microphone.take_part(
                conversation, [GUEST_QUESTION_AUDIO], hang_up_after_event_count=count_events_after_answers(1)
            )

        actual_call_rejections: list[tuple[bool, bool]] = [
            (tool_answer["call_rejected"] is True, expected_problem_phrase in str(tool_answer["problem"]))
            for tool_answer in (json.loads(actual_tool_output.output) for actual_tool_output in collect_tool_outputs(realtime_voice_service_scripted))
        ]
        AsserterConversation.assert_conversation_events_are_as_expected(
            expected_conversation_events=EXPECTED_CONVERSATION_EVENTS, actual_conversation_events=actual_conversation_events
        )
        assert actual_call_rejections == expected_call_rejections

    async def test_Converse_WhenTheAgentCallsToolsWronglyMoreTimesInARowThanAllowed_ThenTheCallEnds(self, restaurant_database_path: Path) -> None:
        guest_microphone: GuestMicrophone = GuestMicrophone()
        wrong_call_count: int = WRONG_CALLS_ALLOWED_IN_A_ROW + 1
        expected_exception_content: ExpectedExceptionContent = ExpectedExceptionContent(
            message_phrases=[f"more than {WRONG_CALLS_ALLOWED_IN_A_ROW} times in a row", f"'{UNKNOWN_TOOL_NAME}'"],
            expected_exception_metadata=ExpectedExceptionMetadata(
                http_status_code=TECHNICAL_FAILURE_HTTP_STATUS_CODE,
                exception_action=ExceptionAction.DEVELOPER_ACTION_REQUIRED,
                reason="The agent kept calling its tools wrongly",
                severity=Severity.ERROR,
                log_event=LogEventAgentTool.TOOL_CALL,
            ),
            contextual_data_by_name={"AgentTool.Name": UNKNOWN_TOOL_NAME, "AgentTool.RepairLimit": WRONG_CALLS_ALLOWED_IN_A_ROW},
        )
        expected_provider_session_count: int = 1
        expected_call_rejection_count: int = WRONG_CALLS_ALLOWED_IN_A_ROW

        async with (
            RealtimeVoiceServiceScripted(
                events_after_each_guest_audio=create_tool_call_events(TOOL_CALL_ID, UNKNOWN_TOOL_NAME, "{}")
            ) as realtime_voice_service_scripted,
            create_domain_facade(realtime_voice_service_scripted, restaurant_database_path) as domain_facade,
            asyncio.timeout(CONVERSATION_TIME_LIMIT_SECONDS),
            aclosing(domain_facade.converse(CONVERSATION_REQUEST, guest_microphone.stream_audio())) as conversation,
        ):
            with pytest.raises(AgentToolCallRepairsExhaustedException) as raised:
                await guest_microphone.take_part(
                    conversation, [GUEST_QUESTION_AUDIO] * wrong_call_count, hang_up_after_event_count=count_events_after_answers(wrong_call_count)
                )

        actual_call_rejection_count: int = sum(
            json.loads(actual_tool_output.output)["call_rejected"] is True
            for actual_tool_output in collect_tool_outputs(realtime_voice_service_scripted)
        )
        AsserterException.assert_technical_failure_is_as_expected(
            expected_exception_content=expected_exception_content,
            expected_provider_session_count=expected_provider_session_count,
            actual_voice_agent_conversation_exception=raised.value,
            actual_captured_realtime_sessions=realtime_voice_service_scripted.captured_realtime_sessions,
        )
        assert actual_call_rejection_count == expected_call_rejection_count

    async def test_Converse_WhenWrongToolCallsAreBrokenUpByAcceptedOnes_ThenTheCallGoesOn(self, restaurant_database_path: Path) -> None:
        # Each question draws one wrong call and then one accepted call, so more wrong calls arrive than are allowed in a
        # row, but never in a row.
        guest_microphone: GuestMicrophone = GuestMicrophone()
        guest_question_count: int = WRONG_CALLS_ALLOWED_IN_A_ROW + 1
        answered_call_count: int = guest_question_count * 2
        expected_conversation_events: list[ConversationEvent] = GREETING_EVENTS + ANSWER_EVENTS * answered_call_count
        expected_answered_call_ids: list[str] = [TOOL_CALL_ID, SECOND_TOOL_CALL_ID] * guest_question_count

        async with (
            RealtimeVoiceServiceScripted(
                events_after_each_guest_audio=[
                    *create_tool_call_events(TOOL_CALL_ID, UNKNOWN_TOOL_NAME, "{}"),
                    *create_tool_call_events(SECOND_TOOL_CALL_ID, "search_menu", KETO_SEARCH_ARGUMENTS_JSON),
                ]
            ) as realtime_voice_service_scripted,
            create_domain_facade(realtime_voice_service_scripted, restaurant_database_path) as domain_facade,
            asyncio.timeout(CONVERSATION_TIME_LIMIT_SECONDS),
            aclosing(domain_facade.converse(CONVERSATION_REQUEST, guest_microphone.stream_audio())) as conversation,
        ):
            actual_conversation_events: list[ConversationEvent] = await guest_microphone.take_part(
                conversation,
                [GUEST_QUESTION_AUDIO] * guest_question_count,
                hang_up_after_event_count=count_events_after_answers(answered_call_count),
            )

        actual_answered_call_ids: list[str] = [
            actual_tool_output.call_id for actual_tool_output in collect_tool_outputs(realtime_voice_service_scripted)
        ]
        AsserterConversation.assert_conversation_events_are_as_expected(
            expected_conversation_events=expected_conversation_events, actual_conversation_events=actual_conversation_events
        )
        assert actual_answered_call_ids == expected_answered_call_ids

    @pytest.mark.parametrize(
        ("reservation_time", "party_size", "expected_reason_phrase"),
        [
            pytest.param("19:00", 10, "private dining room", id="party-too-large-to-book-by-phone"),
            pytest.param("18:40", 2, "the nearest times are 18:30 and 18:45", id="time-between-bookable-times"),
        ],
    )
    async def test_Converse_WhenTheBookingPolicyRefusesTheAgentsRequest_ThenTheAgentIsToldWhySoItCanTellTheCaller(
        self, restaurant_database_path: Path, reservation_time: str, party_size: int, expected_reason_phrase: str
    ) -> None:
        guest_microphone: GuestMicrophone = GuestMicrophone()
        availability_request: AvailabilityRequest = await create_tomorrows_availability_request(
            restaurant_database_path, reservation_time, party_size
        )
        policy_refusal: str = await read_policy_refusal(restaurant_database_path, availability_request)
        assert expected_reason_phrase in policy_refusal, (
            f"The restaurant's refusal no longer gives the reason this scenario needs: {policy_refusal!r}"
        )
        expected_tool_answers: list[dict[str, object]] = [{"refused": True, "reason": policy_refusal}]

        async with (
            RealtimeVoiceServiceScripted(
                events_after_each_guest_audio=create_tool_call_events(TOOL_CALL_ID, "check_availability", json.dumps(asdict(availability_request)))
            ) as realtime_voice_service_scripted,
            create_domain_facade(realtime_voice_service_scripted, restaurant_database_path) as domain_facade,
            asyncio.timeout(CONVERSATION_TIME_LIMIT_SECONDS),
            aclosing(domain_facade.converse(CONVERSATION_REQUEST, guest_microphone.stream_audio())) as conversation,
        ):
            actual_conversation_events: list[ConversationEvent] = await guest_microphone.take_part(
                conversation, [GUEST_QUESTION_AUDIO], hang_up_after_event_count=count_events_after_answers(1)
            )

        actual_tool_answers: list[dict[str, object]] = [
            json.loads(actual_tool_output.output) for actual_tool_output in collect_tool_outputs(realtime_voice_service_scripted)
        ]
        AsserterConversation.assert_conversation_events_are_as_expected(
            expected_conversation_events=EXPECTED_CONVERSATION_EVENTS, actual_conversation_events=actual_conversation_events
        )
        assert actual_tool_answers == expected_tool_answers

    async def test_Converse_WhenTheBookingPolicyRefusesMoreTimesInARowThanWrongCallsAreAllowed_ThenTheCallGoesOn(
        self, restaurant_database_path: Path
    ) -> None:
        # A refusal is the restaurant's answer, not a wrong call by the agent, so it never counts toward the wrong calls
        # allowed. The test above proves the same number of wrong calls in a row would end the call.
        guest_microphone: GuestMicrophone = GuestMicrophone()
        refusal_count: int = WRONG_CALLS_ALLOWED_IN_A_ROW + 1
        availability_request: AvailabilityRequest = await create_tomorrows_availability_request(restaurant_database_path, "19:00", 10)
        policy_refusal: str = await read_policy_refusal(restaurant_database_path, availability_request)
        expected_conversation_events: list[ConversationEvent] = GREETING_EVENTS + ANSWER_EVENTS * refusal_count
        expected_tool_answers: list[dict[str, object]] = [{"refused": True, "reason": policy_refusal}] * refusal_count

        async with (
            RealtimeVoiceServiceScripted(
                events_after_each_guest_audio=create_tool_call_events(TOOL_CALL_ID, "check_availability", json.dumps(asdict(availability_request)))
            ) as realtime_voice_service_scripted,
            create_domain_facade(realtime_voice_service_scripted, restaurant_database_path) as domain_facade,
            asyncio.timeout(CONVERSATION_TIME_LIMIT_SECONDS),
            aclosing(domain_facade.converse(CONVERSATION_REQUEST, guest_microphone.stream_audio())) as conversation,
        ):
            actual_conversation_events: list[ConversationEvent] = await guest_microphone.take_part(
                conversation, [GUEST_QUESTION_AUDIO] * refusal_count, hang_up_after_event_count=count_events_after_answers(refusal_count)
            )

        actual_tool_answers: list[dict[str, object]] = [
            json.loads(actual_tool_output.output) for actual_tool_output in collect_tool_outputs(realtime_voice_service_scripted)
        ]
        AsserterConversation.assert_conversation_events_are_as_expected(
            expected_conversation_events=expected_conversation_events, actual_conversation_events=actual_conversation_events
        )
        assert actual_tool_answers == expected_tool_answers
