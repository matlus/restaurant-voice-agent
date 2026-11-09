# Acceptance tests for the tools the agent calls during a conversation, black-box through the conversation DomainFacade.
# The scripted Realtime service plays the speech model: once the guest speaks, it calls one tool and ends that reply
# without speech. The tool runs against the real restaurant store, and the service captures the answer sent back.
# Every expected answer is read from the restaurant itself before the call.

import asyncio
import json
from contextlib import aclosing
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Final

import pytest
from conversation_acceptance_support.asserters.asserter_conversation import AsserterConversation
from conversation_acceptance_support.guest_microphone import GuestMicrophone
from conversation_acceptance_support.realtime_voice_service_scripted import (
    SCRIPTED_GREETING_AUDIO,
    CapturedToolOutput,
    RealtimeVoiceServiceScripted,
    create_tool_call_events,
)
from conversation_acceptance_support.service_locator_testing import create_domain_facade, create_restaurant_domain_facade

from voice_agent_conversation import (
    AgentSpeechChunk,
    AgentTurnFinished,
    ConversationAudioFormat,
    ConversationEvent,
    ConversationRequest,
    ConversationStarted,
    PresentedGender,
    SpeechProvider,
    VoiceOption,
)
from voice_agent_restaurant import (
    AvailabilityRequest,
    ClosedWeekday,
    Dish,
    MenuSearchRequest,
    OpeningHours,
    RestaurantClosedOnDateException,
    Weekday,
)

CEDAR_VOICE_OPTION: Final[VoiceOption] = VoiceOption(
    "openai-cedar", SpeechProvider.OPENAI, "cedar", PresentedGender.MALE, "Calm and grounded, with a low register."
)
PROVIDER_AUDIO_FORMAT: Final[ConversationAudioFormat] = ConversationAudioFormat(guest_audio_sample_rate_hz=24_000, agent_audio_sample_rate_hz=24_000)
GUEST_QUESTION_AUDIO: Final[bytes] = b"guest asks the agent something"
CONVERSATION_TIME_LIMIT_SECONDS: Final[float] = 5.0
TOOL_CALL_ID: Final[str] = "call_guest_question"
# The greeting, then the reply the agent gives once its tool call is answered.
EXPECTED_CONVERSATION_EVENTS: Final[list[ConversationEvent]] = [
    ConversationStarted(audio_format=PROVIDER_AUDIO_FORMAT, voice_option=CEDAR_VOICE_OPTION),
    AgentSpeechChunk(pcm_audio=SCRIPTED_GREETING_AUDIO),
    AgentTurnFinished(),
    AgentSpeechChunk(pcm_audio=SCRIPTED_GREETING_AUDIO),
    AgentTurnFinished(),
]
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


async def hold_tool_call_conversation(
    restaurant_database_path: Path, tool_name: str, arguments_json: str
) -> tuple[list[ConversationEvent], RealtimeVoiceServiceScripted]:
    """A call in which the guest asks one question and the model answers it by calling the given tool."""
    guest_microphone: GuestMicrophone = GuestMicrophone()
    async with (
        RealtimeVoiceServiceScripted(
            events_after_each_guest_audio=create_tool_call_events(TOOL_CALL_ID, tool_name, arguments_json)
        ) as realtime_voice_service_scripted,
        create_domain_facade(realtime_voice_service_scripted, restaurant_database_path) as domain_facade,
        asyncio.timeout(CONVERSATION_TIME_LIMIT_SECONDS),
        aclosing(
            domain_facade.converse(ConversationRequest(voice_key=CEDAR_VOICE_OPTION.voice_key), guest_microphone.stream_audio())
        ) as conversation,
    ):
        actual_conversation_events: list[ConversationEvent] = await guest_microphone.take_part(
            conversation, [GUEST_QUESTION_AUDIO], hang_up_after_event_count=len(EXPECTED_CONVERSATION_EVENTS)
        )
    return actual_conversation_events, realtime_voice_service_scripted


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


def find_next_closed_date(restaurant_local_now: datetime, opening_hours: OpeningHours) -> date:
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
            aclosing(
                domain_facade.converse(ConversationRequest(voice_key=CEDAR_VOICE_OPTION.voice_key), guest_microphone.stream_audio())
            ) as conversation,
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
        async with create_restaurant_domain_facade(restaurant_database_path) as restaurant_domain_facade:
            keto_dishes: list[Dish] = await restaurant_domain_facade.search_menu(
                MenuSearchRequest(diet_labels=["keto"], excluded_allergens=[], category=None, maximum_calories=None, search_text=None)
            )
        assert keto_dishes, "The menu must hold keto dishes for this scenario; the seeded data no longer supports it"
        expected_tool_answer: tuple[list[str], list[str]] = ([TOOL_CALL_ID], [keto_dish.dish_id for keto_dish in keto_dishes])
        expected_agent_response_request_count: int = 2

        actual_conversation_events: list[ConversationEvent]
        realtime_voice_service_scripted: RealtimeVoiceServiceScripted
        actual_conversation_events, realtime_voice_service_scripted = await hold_tool_call_conversation(
            restaurant_database_path, "search_menu", '{"diet_labels": ["keto"]}'
        )

        actual_tool_outputs: list[CapturedToolOutput] = collect_tool_outputs(realtime_voice_service_scripted)
        actual_tool_answer: tuple[list[str], list[str]] = (
            [actual_tool_output.call_id for actual_tool_output in actual_tool_outputs],
            [answered_dish["dish_id"] for actual_tool_output in actual_tool_outputs for answered_dish in json.loads(actual_tool_output.output)],
        )
        AsserterConversation.assert_conversation_events_are_as_expected(
            expected_conversation_events=EXPECTED_CONVERSATION_EVENTS, actual_conversation_events=actual_conversation_events
        )
        assert (actual_tool_answer, count_agent_response_requests(realtime_voice_service_scripted)) == (
            expected_tool_answer,
            expected_agent_response_request_count,
        )

    async def test_Converse_WhenTheAgentGoesOnAfterALookup_ThenOnlyItsFirstReplyWasToldToGreet(self, restaurant_database_path: Path) -> None:
        # The greeting instruction once lived in the standing instructions the model reads before every reply, and the
        # model greeted again when asked to go on after a lookup. Now only the first reply request carries it.
        greeting_marker: str = "Greet the caller"
        expected_greeting_placement: tuple[list[bool], bool] = ([True, False], False)

        realtime_voice_service_scripted: RealtimeVoiceServiceScripted
        _, realtime_voice_service_scripted = await hold_tool_call_conversation(restaurant_database_path, "search_menu", '{"diet_labels": ["keto"]}')

        captured_realtime_session = realtime_voice_service_scripted.captured_realtime_sessions[0]
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
        async with create_restaurant_domain_facade(restaurant_database_path) as restaurant_domain_facade:
            restaurant_local_now: datetime = await restaurant_domain_facade.get_restaurant_local_now()
            closed_date: date = find_next_closed_date(restaurant_local_now, await restaurant_domain_facade.get_opening_hours())
            availability_request: AvailabilityRequest = AvailabilityRequest(
                reservation_date=closed_date.isoformat(), reservation_time="19:00", party_size=2
            )
            with pytest.raises(RestaurantClosedOnDateException) as raised:
                await restaurant_domain_facade.check_availability(availability_request)
        expected_tool_answers: list[dict[str, object]] = [{"refused": True, "reason": raised.value.message}]

        actual_conversation_events: list[ConversationEvent]
        realtime_voice_service_scripted: RealtimeVoiceServiceScripted
        actual_conversation_events, realtime_voice_service_scripted = await hold_tool_call_conversation(
            restaurant_database_path,
            "check_availability",
            json.dumps({"reservation_date": closed_date.isoformat(), "reservation_time": "19:00", "party_size": 2}),
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
            pytest.param("order_pizza", "{}", "no tool named 'order_pizza'", id="unknown-tool"),
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
        expected_call_rejections: list[tuple[bool, bool]] = [(True, True)]

        actual_conversation_events: list[ConversationEvent]
        realtime_voice_service_scripted: RealtimeVoiceServiceScripted
        actual_conversation_events, realtime_voice_service_scripted = await hold_tool_call_conversation(
            restaurant_database_path, tool_name, arguments_json
        )

        actual_call_rejections: list[tuple[bool, bool]] = [
            (tool_answer["call_rejected"] is True, expected_problem_phrase in str(tool_answer["problem"]))
            for tool_answer in (json.loads(actual_tool_output.output) for actual_tool_output in collect_tool_outputs(realtime_voice_service_scripted))
        ]
        AsserterConversation.assert_conversation_events_are_as_expected(
            expected_conversation_events=EXPECTED_CONVERSATION_EVENTS, actual_conversation_events=actual_conversation_events
        )
        assert actual_call_rejections == expected_call_rejections
