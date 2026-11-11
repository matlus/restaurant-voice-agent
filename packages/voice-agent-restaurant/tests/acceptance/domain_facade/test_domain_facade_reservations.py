# Acceptance tests for availability and the reservation lifecycle: book, find, change, cancel.
# Black-box through the DomainFacade against a real SQLite store seeded from the bundled seed files.
#
# "Now" is Wednesday 2026-11-04 15:00 in Riverton unless a test says otherwise. The seed fills every 4-top around 19:00
# on Friday 2026-11-06, so a party of 4 cannot sit at 19:00 that evening. Tests pin a seeded booking by its phone number,
# find it as its guest does, by that number, the name it is under and its date, and derive their expectations from what
# they read; the open times a refusal must offer are worked out from the restaurant's own availability answers for every
# other bookable time that day.

import asyncio
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Final
from zoneinfo import ZoneInfo

import pytest

from acceptance_support.asserters.asserter_exception import AsserterException, ExpectedExceptionContent, ExpectedExceptionMetadata
from acceptance_support.asserters.asserter_reservation import AsserterReservation, ExpectedNewReservation
from acceptance_support.bundled_seed import (
    SeededBookingGuest,
    SeededOpenWeekday,
    SeededRestaurant,
    SeededTable,
    read_seeded_booking_guest,
    read_seeded_restaurant,
    read_seeded_tables,
)
from acceptance_support.generated_guests import GeneratedGuest, create_generated_guest, create_generated_note
from acceptance_support.seeded_bookings import derive_next_weekday_date, retrieve_seeded_booking
from acceptance_support.service_locator_testing import (
    FRIDAY_EVENING_UTC,
    THURSDAY_EARLY_EVENING_UTC,
    create_domain_facade,
    create_domain_facade_without_demo_bookings,
)
from voice_agent_restaurant import (
    AvailabilityRequest,
    AvailabilityResult,
    Closure,
    ConfirmationCodeReference,
    DomainFacade,
    ExceptionAction,
    GuestDetailsReference,
    GuestReservationNotFoundException,
    LogEventReservation,
    NoTableAvailableException,
    OpeningHours,
    OpenWeekday,
    OutsideSeatingHoursException,
    Reservation,
    ReservationAlreadyStartedException,
    ReservationCancellationRequest,
    ReservationChangeRequest,
    ReservationNotFoundException,
    ReservationPolicy,
    ReservationPolicyRefusedException,
    ReservationRequest,
    ReservationRequestValidationException,
    ReservationSearchRequest,
    ReservationStatus,
    RestaurantClosedOnDateException,
    RestaurantProfile,
    Severity,
    Weekday,
)

BUSY_FRIDAY: Final[str] = "2026-11-06"
QUIET_THURSDAY: Final[str] = "2026-11-05"
CLOSED_MONDAY: Final[str] = "2026-11-09"
# The seed books every table all evening on Tuesday, and leaves Wednesday, today, with only two times for up to four.
FULLY_BOOKED_TUESDAY: Final[str] = "2026-11-10"
NEARLY_FULL_WEDNESDAY: Final[str] = "2026-11-04"
SEEDED_PRIYA_PHONE: Final[str] = "5550101001"
# Sunday 2026-12-20 at 15:00 in Riverton: the Friday after it is Christmas Day, and the one after that New Year's Day.
SUNDAY_BEFORE_CHRISTMAS_UTC: Final[datetime] = datetime(2026, 12, 20, 21, 0, tzinfo=UTC)
SEEDED_SAM_PHONE: Final[str] = "5550101010"
FULLWIDTH_DIGIT_ZERO_CODE_POINT: Final[int] = 0xFF10
SEEDED_PRIYA_PHONE_IN_FULLWIDTH_DIGITS: Final[str] = "".join(chr(FULLWIDTH_DIGIT_ZERO_CODE_POINT + int(digit)) for digit in SEEDED_PRIYA_PHONE)
# A refusal offers at most this many other open times, the ones nearest to the time asked for.
OFFERED_ALTERNATIVE_TIME_COUNT: Final[int] = 3
MINUTES_PER_HOUR: Final[int] = 60
NOON_HOUR: Final[int] = 12
RESERVATION_VALIDATION_REFUSAL_REASON: Final[str] = "Reservation request failed validation"
RESERVATION_POLICY_REFUSAL_REASON: Final[str] = "Reservation request is not allowed by the booking policy"
RESERVATION_DATE_CONTEXT_NAME: Final[str] = "Reservation.Date"
RESERVATION_PARTY_SIZE_CONTEXT_NAME: Final[str] = "Reservation.PartySize"
RESERVATION_PROBLEM_COUNT_CONTEXT_NAME: Final[str] = "Reservation.ProblemCount"
CONFIRMATION_CODE_CONTEXT_NAME: Final[str] = "Reservation.ConfirmationCode"


def create_reservation_request(
    generated_guest: GeneratedGuest,
    reservation_date: str = QUIET_THURSDAY,
    reservation_time: str = "19:00",
    party_size: int = 2,
    notes: str | None = None,
) -> ReservationRequest:
    return ReservationRequest(
        guest_name=generated_guest.guest_name,
        phone_number=generated_guest.phone_number_with_brackets,
        party_size=party_size,
        reservation_date=reservation_date,
        reservation_time=reservation_time,
        notes=notes,
    )


def create_change_request(
    confirmation_code: str | None,
    phone_number: str | None,
    reservation_date: str | None = None,
    reservation_time: str | None = None,
    party_size: int | None = None,
    notes: str | None = None,
) -> ReservationChangeRequest:
    return ReservationChangeRequest(
        booking_reference=ConfirmationCodeReference(confirmation_code=confirmation_code, phone_number=phone_number),
        reservation_date=reservation_date,
        reservation_time=reservation_time,
        party_size=party_size,
        notes=notes,
    )


def create_guest_change_request(current_reservation: Reservation, guest_name: str, reservation_time: str) -> ReservationChangeRequest:
    """A change to a new time from a guest without the code, who names the booking by everything it is booked under."""
    return ReservationChangeRequest(
        booking_reference=create_guest_details_reference(current_reservation, guest_name, f"{current_reservation.starts_at:%H:%M}"),
        reservation_date=None,
        reservation_time=reservation_time,
        party_size=None,
        notes=None,
    )


def create_guest_details_reference(current_reservation: Reservation, guest_name: str, booked_time: str) -> GuestDetailsReference:
    """The booking as a guest without the code names it: its phone number and date, with the name and time as they say them."""
    return GuestDetailsReference(
        phone_number=current_reservation.phone_number,
        guest_name=guest_name,
        booked_date=current_reservation.reservation_date.isoformat(),
        booked_time=booked_time,
    )


def create_code_cancellation_request(confirmation_code: str, phone_number: str | None) -> ReservationCancellationRequest:
    return ReservationCancellationRequest(booking_reference=ConfirmationCodeReference(confirmation_code=confirmation_code, phone_number=phone_number))


def create_guest_cancellation_request(current_reservation: Reservation, guest_name: str, booked_time: str) -> ReservationCancellationRequest:
    return ReservationCancellationRequest(booking_reference=create_guest_details_reference(current_reservation, guest_name, booked_time))


def create_search_request(phone_number: str, guest_name: str, reservation_date: date) -> ReservationSearchRequest:
    return ReservationSearchRequest(phone_number=phone_number, guest_name=guest_name, reservation_date=reservation_date.isoformat())


def create_booking_search_request(reservation: Reservation) -> ReservationSearchRequest:
    """The search a guest makes to find this booking again: its own phone number, name and date."""
    return create_search_request(reservation.phone_number, reservation.guest_name, reservation.reservation_date)


def create_guest_not_found_metadata() -> ExpectedExceptionMetadata:
    return ExpectedExceptionMetadata(
        http_status_code=404,
        exception_action=ExceptionAction.USER_ACTION_REQUIRED,
        reason="The reservation was not found",
        severity=Severity.ERROR,
        log_event=LogEventReservation.RESERVATION_LOOKUP,
    )


def create_validation_refusal_metadata() -> ExpectedExceptionMetadata:
    return ExpectedExceptionMetadata(
        http_status_code=400,
        exception_action=ExceptionAction.USER_ACTION_REQUIRED,
        reason=RESERVATION_VALIDATION_REFUSAL_REASON,
        severity=Severity.ERROR,
        log_event=LogEventReservation.RESERVATION_REQUEST_VALIDATION_FAILED,
    )


def create_policy_refusal_metadata() -> ExpectedExceptionMetadata:
    return ExpectedExceptionMetadata(
        http_status_code=400,
        exception_action=ExceptionAction.USER_ACTION_REQUIRED,
        reason=RESERVATION_POLICY_REFUSAL_REASON,
        severity=Severity.ERROR,
        log_event=LogEventReservation.RESERVATION_POLICY_REFUSED,
    )


@dataclass(frozen=True)
class BookingWindowBreach:
    requested_start: datetime
    expected_problem_phrase: str


async def retrieve_unstarted_seeded_booking(domain_facade: DomainFacade, phone_number: str, scenario: str) -> Reservation:
    """The seeded booking for the phone number, guarded to start after the restaurant's local now, because a booking
    that has started can no longer be changed or cancelled."""
    seeded_reservation: Reservation = await retrieve_seeded_booking(domain_facade, phone_number)
    restaurant_local_now: datetime = await domain_facade.get_restaurant_local_now()
    seeded_start: datetime = datetime.combine(seeded_reservation.reservation_date, seeded_reservation.starts_at, tzinfo=restaurant_local_now.tzinfo)
    assert seeded_start > restaurant_local_now, (
        f"{scenario} needs booking {seeded_reservation.confirmation_code} to start after {restaurant_local_now}, but it starts at "
        f"{seeded_start}; the seeded data no longer supports this scenario"
    )
    return seeded_reservation


def derive_booking_window_breach(
    booking_window_edge: str, restaurant_local_now: datetime, reservation_policy: ReservationPolicy
) -> BookingWindowBreach:
    """A bookable-looking start that breaks the booking window at the given edge, with the problem the refusal must name."""
    if booking_window_edge == "already passed":
        return BookingWindowBreach(
            requested_start=datetime.combine(restaurant_local_now.date() - timedelta(days=1), time(19, 0), tzinfo=restaurant_local_now.tzinfo),
            expected_problem_phrase="has already passed",
        )
    return BookingWindowBreach(
        requested_start=datetime.combine(
            restaurant_local_now.date() + timedelta(days=reservation_policy.booking_window_days + 1),
            time(19, 0),
            tzinfo=restaurant_local_now.tzinfo,
        ),
        expected_problem_phrase=f"more than {reservation_policy.booking_window_days} days ahead",
    )


async def derive_offered_open_times(domain_facade: DomainFacade, reservation_date: date, requested_time: time, party_size: int) -> list[time]:
    """The open times a refusal must offer, worked out as the guest is promised them: every other bookable time that day
    the restaurant reports as available for the party, the OFFERED_ALTERNATIVE_TIME_COUNT nearest to the time asked for,
    in time order."""
    restaurant_profile: RestaurantProfile = await domain_facade.get_restaurant_profile()
    opening_hours: OpeningHours = await domain_facade.get_opening_hours()
    requested_weekday: Weekday = list(Weekday)[reservation_date.weekday()]
    open_weekdays: list[OpenWeekday] = [
        weekday_hours
        for weekday_hours in opening_hours.weekly_hours
        if isinstance(weekday_hours, OpenWeekday) and weekday_hours.weekday == requested_weekday
    ]
    assert len(open_weekdays) == 1, f"The restaurant must open on {requested_weekday.value}s for this scenario; the seeded data no longer supports it"
    first_seating_minutes: int = to_minutes(open_weekdays[0].opens_at)
    last_seating_minutes: int = to_minutes(open_weekdays[0].closes_at) - opening_hours.last_seating_minutes_before_close
    open_times: list[time] = []
    slot_minutes: int
    for slot_minutes in range(first_seating_minutes, last_seating_minutes + 1, restaurant_profile.reservation_policy.slot_interval_minutes):
        slot_time: time = to_time(slot_minutes)
        if slot_time == requested_time:
            continue
        availability_result: AvailabilityResult = await domain_facade.check_availability(
            AvailabilityRequest(reservation_date=reservation_date.isoformat(), reservation_time=f"{slot_time:%H:%M}", party_size=party_size)
        )
        if availability_result.is_available:
            open_times.append(slot_time)
    nearest_open_times: list[time] = sorted(open_times, key=lambda open_time: abs(to_minutes(open_time) - to_minutes(requested_time)))
    return sorted(nearest_open_times[:OFFERED_ALTERNATIVE_TIME_COUNT])


async def derive_busy_friday_open_times(domain_facade: DomainFacade, requested_time: time, party_size: int) -> list[time]:
    """The open times a refusal on the busy Friday must offer, guarded to be a full set, so that a refusal offering no
    times at all could not pass as matching."""
    busy_friday_open_times: list[time] = await derive_offered_open_times(domain_facade, date.fromisoformat(BUSY_FRIDAY), requested_time, party_size)
    assert len(busy_friday_open_times) == OFFERED_ALTERNATIVE_TIME_COUNT, (
        f"The busy Friday needs {OFFERED_ALTERNATIVE_TIME_COUNT} open times near {requested_time:%H:%M} for a party of {party_size}; "
        f"the seeded data no longer supports this scenario: {busy_friday_open_times!r}"
    )
    return busy_friday_open_times


def retrieve_smallest_fitting_table_id(party_size: int) -> str:
    """The table a new booking takes when every table is free: the fewest seats that hold the party, then the lowest table id."""
    fitting_tables: list[SeededTable] = [seeded_table for seeded_table in read_seeded_tables() if seeded_table.seats >= party_size]
    assert fitting_tables, f"The seeded tables must hold a party of {party_size}; the seeded data no longer supports this scenario"
    return min(fitting_tables, key=lambda fitting_table: (fitting_table.seats, fitting_table.table_id)).table_id


def retrieve_seeded_open_weekday(seeded_restaurant: SeededRestaurant, weekday: Weekday) -> SeededOpenWeekday:
    seeded_open_weekdays: list[SeededOpenWeekday] = [
        seeded_weekday_hours
        for seeded_weekday_hours in seeded_restaurant.weekly_hours
        if isinstance(seeded_weekday_hours, SeededOpenWeekday) and seeded_weekday_hours.weekday == weekday.value
    ]
    assert len(seeded_open_weekdays) == 1, f"The restaurant must open on {weekday.value} for this scenario; the seeded data no longer supports it"
    return seeded_open_weekdays[0]


def to_minutes(time_of_day: time) -> int:
    return time_of_day.hour * MINUTES_PER_HOUR + time_of_day.minute


def to_time(minutes_after_midnight: int) -> time:
    return time(hour=minutes_after_midnight // MINUTES_PER_HOUR, minute=minutes_after_midnight % MINUTES_PER_HOUR)


def say_phone_number_with_separators(phone_digits: str) -> str:
    return f"({phone_digits[0:3]}) {phone_digits[3:6]}-{phone_digits[6:]}"


class TestCheckAvailability:
    async def test_CheckAvailability_WhenASmallerTableIsFree_ThenTheTimeIsAvailableWithNoAlternatives(self, restaurant_database_path: Path) -> None:
        expected_availability_result: AvailabilityResult = AvailabilityResult(
            reservation_date=date(2026, 11, 6), requested_time=time(19, 0), party_size=2, is_available=True, alternative_times=[]
        )

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            actual_availability_result: AvailabilityResult = await domain_facade.check_availability(
                AvailabilityRequest(reservation_date=BUSY_FRIDAY, reservation_time="19:00", party_size=2)
            )

        assert actual_availability_result == expected_availability_result

    @pytest.mark.parametrize("spoken_time", ["6:30 PM", "6:30pm", "6:30 p.m.", "6:30", "06:30"])
    async def test_CheckAvailability_WhenADinnerTimeIsSaidAsCallersSayIt_ThenItIsReadAsTheEveningTime(
        self, restaurant_database_path: Path, spoken_time: str
    ) -> None:
        expected_requested_time: time = time(18, 30)

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            actual_availability_result: AvailabilityResult = await domain_facade.check_availability(
                AvailabilityRequest(reservation_date=QUIET_THURSDAY, reservation_time=spoken_time, party_size=2)
            )

        assert actual_availability_result.requested_time == expected_requested_time

    async def test_CheckAvailability_WhenEveryFittingTableIsTaken_ThenTheThreeNearestOpenTimesAreOffered(
        self, restaurant_database_path: Path
    ) -> None:
        busy_friday: date = date.fromisoformat(BUSY_FRIDAY)
        requested_time: time = time(19, 0)
        party_size: int = 4

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            expected_availability_result: AvailabilityResult = AvailabilityResult(
                reservation_date=busy_friday,
                requested_time=requested_time,
                party_size=party_size,
                is_available=False,
                alternative_times=await derive_busy_friday_open_times(domain_facade, requested_time, party_size),
            )
            actual_availability_result: AvailabilityResult = await domain_facade.check_availability(
                AvailabilityRequest(reservation_date=BUSY_FRIDAY, reservation_time=f"{requested_time:%H:%M}", party_size=party_size)
            )

        assert actual_availability_result == expected_availability_result

    async def test_CheckAvailability_WhenEveryTableIsTakenAllEvening_ThenNoOtherTimeIsOffered(self, restaurant_database_path: Path) -> None:
        expected_availability_result: AvailabilityResult = AvailabilityResult(
            reservation_date=date.fromisoformat(FULLY_BOOKED_TUESDAY),
            requested_time=time(19, 0),
            party_size=2,
            is_available=False,
            alternative_times=[],
        )

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            actual_availability_result: AvailabilityResult = await domain_facade.check_availability(
                AvailabilityRequest(reservation_date=FULLY_BOOKED_TUESDAY, reservation_time="19:00", party_size=2)
            )

        assert actual_availability_result == expected_availability_result

    async def test_CheckAvailability_WhenOnlyTwoTimesAreLeft_ThenThoseTwoAreOffered(self, restaurant_database_path: Path) -> None:
        nearly_full_wednesday: date = date.fromisoformat(NEARLY_FULL_WEDNESDAY)
        requested_time: time = time(19, 0)
        party_size: int = 2

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            open_times: list[time] = await derive_offered_open_times(domain_facade, nearly_full_wednesday, requested_time, party_size)
            assert len(open_times) == 2, (
                f"The nearly full Wednesday needs exactly two open times for a party of {party_size}; the seeded data no longer supports "
                f"this scenario: {open_times!r}"
            )
            expected_availability_result: AvailabilityResult = AvailabilityResult(
                reservation_date=nearly_full_wednesday,
                requested_time=requested_time,
                party_size=party_size,
                is_available=False,
                alternative_times=open_times,
            )
            actual_availability_result: AvailabilityResult = await domain_facade.check_availability(
                AvailabilityRequest(reservation_date=NEARLY_FULL_WEDNESDAY, reservation_time="19:00", party_size=2)
            )

        assert actual_availability_result == expected_availability_result

    async def test_CheckAvailability_WhenTheRestaurantDoesNotOpenThatWeekday_ThenTheRefusalSaysItIsClosed(
        self, restaurant_database_path: Path
    ) -> None:
        expected_message_phrases: list[str] = [CLOSED_MONDAY, "closed on Mondays"]
        expected_exception_metadata: ExpectedExceptionMetadata = ExpectedExceptionMetadata(
            http_status_code=400,
            exception_action=ExceptionAction.USER_ACTION_REQUIRED,
            reason="The restaurant is closed on the requested date",
            severity=Severity.ERROR,
            log_event=LogEventReservation.RESERVATION_SCHEDULING,
        )
        expected_contextual_data_by_name: dict[str, str] = {RESERVATION_DATE_CONTEXT_NAME: CLOSED_MONDAY}

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            with pytest.raises(RestaurantClosedOnDateException) as raised:
                await domain_facade.check_availability(AvailabilityRequest(reservation_date=CLOSED_MONDAY, reservation_time="19:00", party_size=2))

        AsserterException.assert_message_and_metadata_are_as_expected(
            expected_exception_content=ExpectedExceptionContent(
                message_phrases=expected_message_phrases,
                exception_metadata=expected_exception_metadata,
                contextual_data_by_name=expected_contextual_data_by_name,
            ),
            actual_voice_agent_restaurant_exception=raised.value,
        )

    async def test_CheckAvailability_WhenTheDateIsAHolidayClosure_ThenTheRefusalNamesTheHoliday(self, restaurant_database_path: Path) -> None:
        expected_exception_metadata: ExpectedExceptionMetadata = ExpectedExceptionMetadata(
            http_status_code=400,
            exception_action=ExceptionAction.USER_ACTION_REQUIRED,
            reason="The restaurant is closed on the requested date",
            severity=Severity.ERROR,
            log_event=LogEventReservation.RESERVATION_SCHEDULING,
        )

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            opening_hours: OpeningHours = await domain_facade.get_opening_hours()
            upcoming_closure: Closure = opening_hours.upcoming_closures[0]
            expected_message_phrases: list[str] = [upcoming_closure.closed_on.isoformat(), upcoming_closure.reason]
            expected_contextual_data_by_name: dict[str, str] = {RESERVATION_DATE_CONTEXT_NAME: upcoming_closure.closed_on.isoformat()}
            with pytest.raises(RestaurantClosedOnDateException) as raised:
                await domain_facade.check_availability(
                    AvailabilityRequest(reservation_date=upcoming_closure.closed_on.isoformat(), reservation_time="19:00", party_size=2)
                )

        AsserterException.assert_message_and_metadata_are_as_expected(
            expected_exception_content=ExpectedExceptionContent(
                message_phrases=expected_message_phrases,
                exception_metadata=expected_exception_metadata,
                contextual_data_by_name=expected_contextual_data_by_name,
            ),
            actual_voice_agent_restaurant_exception=raised.value,
        )
        assert raised.value.closure_reason == upcoming_closure.reason

    async def test_CheckAvailability_WhenTheTimeLeavesTooLittleBeforeClosing_ThenTheRefusalGivesTheSeatingHours(
        self, restaurant_database_path: Path
    ) -> None:
        # The last table is seated one full seating before closing; the request is one slot later than that.
        seeded_restaurant: SeededRestaurant = read_seeded_restaurant()
        friday_seeded_open_weekday: SeededOpenWeekday = retrieve_seeded_open_weekday(seeded_restaurant, Weekday.FRIDAY)
        first_seating_time: time = friday_seeded_open_weekday.opens_at
        last_seating_time: time = to_time(
            to_minutes(friday_seeded_open_weekday.closes_at) - seeded_restaurant.reservation_policy.seating_duration_minutes
        )
        requested_time: str = f"{to_time(to_minutes(last_seating_time) + seeded_restaurant.reservation_policy.slot_interval_minutes):%H:%M}"
        expected_seating_hours: tuple[time, time] = (first_seating_time, last_seating_time)
        expected_message_phrases: list[str] = [
            requested_time,
            "outside seating hours",
            BUSY_FRIDAY,
            f"{first_seating_time:%H:%M}",
            f"{last_seating_time:%H:%M}",
        ]
        expected_exception_metadata: ExpectedExceptionMetadata = ExpectedExceptionMetadata(
            http_status_code=400,
            exception_action=ExceptionAction.USER_ACTION_REQUIRED,
            reason="The requested time is outside seating hours",
            severity=Severity.ERROR,
            log_event=LogEventReservation.RESERVATION_SCHEDULING,
        )
        expected_contextual_data_by_name: dict[str, str] = {RESERVATION_DATE_CONTEXT_NAME: BUSY_FRIDAY}

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            with pytest.raises(OutsideSeatingHoursException) as raised:
                await domain_facade.check_availability(
                    AvailabilityRequest(reservation_date=BUSY_FRIDAY, reservation_time=requested_time, party_size=2)
                )

        AsserterException.assert_message_and_metadata_are_as_expected(
            expected_exception_content=ExpectedExceptionContent(
                message_phrases=expected_message_phrases,
                exception_metadata=expected_exception_metadata,
                contextual_data_by_name=expected_contextual_data_by_name,
            ),
            actual_voice_agent_restaurant_exception=raised.value,
        )
        assert (raised.value.first_seating_time, raised.value.last_seating_time) == expected_seating_hours


class TestDemoBookings:
    async def test_CheckAvailability_WhenDemoBookingsAreNotSeeded_ThenTheEveningTheDemoFillsIsFree(self, restaurant_database_path: Path) -> None:
        # The demo bookings fill every table on this evening; a store without them starts with no bookings at all.
        expected_availability_result: AvailabilityResult = AvailabilityResult(
            reservation_date=date.fromisoformat(FULLY_BOOKED_TUESDAY),
            requested_time=time(19, 0),
            party_size=2,
            is_available=True,
            alternative_times=[],
        )

        async with create_domain_facade_without_demo_bookings(restaurant_database_path) as domain_facade:
            actual_availability_result: AvailabilityResult = await domain_facade.check_availability(
                AvailabilityRequest(reservation_date=FULLY_BOOKED_TUESDAY, reservation_time="19:00", party_size=2)
            )

        assert actual_availability_result == expected_availability_result


class TestCreateReservation:
    async def test_CreateReservation_WhenATableIsFree_ThenTheSmallestFittingTableIsBookedAndCanBeFoundByPhone(
        self, restaurant_database_path: Path
    ) -> None:
        generated_guest: GeneratedGuest = create_generated_guest()
        generated_note: str = create_generated_note()
        party_size: int = 2
        reservation_date: date = date.fromisoformat(QUIET_THURSDAY)
        starts_at: time = time(19, 0)
        seating_duration_minutes: int = read_seeded_restaurant().reservation_policy.seating_duration_minutes
        expected_new_reservation: ExpectedNewReservation = ExpectedNewReservation(
            guest_name=generated_guest.guest_name,
            phone_number=generated_guest.phone_digits,
            party_size=party_size,
            reservation_date=reservation_date,
            starts_at=starts_at,
            ends_at=(datetime.combine(reservation_date, starts_at) + timedelta(minutes=seating_duration_minutes)).time(),
            table_id=retrieve_smallest_fitting_table_id(party_size),
            notes=generated_note,
            reservation_status=ReservationStatus.BOOKED,
        )

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            actual_reservation: Reservation = await domain_facade.create_reservation(
                create_reservation_request(
                    generated_guest,
                    reservation_date=QUIET_THURSDAY,
                    reservation_time=f"{starts_at:%H:%M}",
                    party_size=party_size,
                    notes=f"  {generated_note} ",
                )
            )
            actual_found_reservations: list[Reservation] = await domain_facade.find_reservations(
                create_search_request(generated_guest.phone_number_with_country_code, generated_guest.guest_name, date.fromisoformat(QUIET_THURSDAY))
            )

        AsserterReservation.assert_new_reservation_is_as_expected(expected_new_reservation, actual_reservation)
        assert actual_found_reservations == [actual_reservation]

    async def test_CreateReservation_WhenTonightsDinnerTimeIsSaidWithoutPm_ThenTheEveningSeatingIsBookedNotRefusedAsPassed(
        self, restaurant_database_path: Path
    ) -> None:
        # Today is NEARLY_FULL_WEDNESDAY, mid-afternoon, so read as morning, "6:30" would already have passed.
        generated_guest: GeneratedGuest = create_generated_guest()
        spoken_time: str = "6:30"
        nearly_full_wednesday: date = date.fromisoformat(NEARLY_FULL_WEDNESDAY)
        evening_seating: time = time(18, 30)
        expected_booked_seating: tuple[date, time] = (nearly_full_wednesday, evening_seating)

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            evening_availability_result: AvailabilityResult = await domain_facade.check_availability(
                AvailabilityRequest(reservation_date=NEARLY_FULL_WEDNESDAY, reservation_time=f"{evening_seating:%H:%M}", party_size=2)
            )
            assert evening_availability_result.is_available, (
                f"Reading '{spoken_time}' as the evening needs a free table at {evening_seating:%H:%M} on {NEARLY_FULL_WEDNESDAY}; "
                f"the seeded data no longer supports this scenario: {evening_availability_result!r}"
            )
            actual_reservation: Reservation = await domain_facade.create_reservation(
                create_reservation_request(generated_guest, reservation_date=NEARLY_FULL_WEDNESDAY, reservation_time=spoken_time)
            )

        assert (actual_reservation.reservation_date, actual_reservation.starts_at) == expected_booked_seating

    async def test_CreateReservation_WhenATableIsFreeMinutesFromNow_ThenItIsBooked(self, restaurant_database_path: Path) -> None:
        generated_guest: GeneratedGuest = create_generated_guest()
        party_size: int = 2
        reservation_date: date = date.fromisoformat(QUIET_THURSDAY)
        starts_at: time = time(19, 0)
        seating_duration_minutes: int = read_seeded_restaurant().reservation_policy.seating_duration_minutes
        expected_new_reservation: ExpectedNewReservation = ExpectedNewReservation(
            guest_name=generated_guest.guest_name,
            phone_number=generated_guest.phone_digits,
            party_size=party_size,
            reservation_date=reservation_date,
            starts_at=starts_at,
            ends_at=(datetime.combine(reservation_date, starts_at) + timedelta(minutes=seating_duration_minutes)).time(),
            table_id=retrieve_smallest_fitting_table_id(party_size),
            notes=None,
            reservation_status=ReservationStatus.BOOKED,
        )

        async with create_domain_facade(restaurant_database_path, THURSDAY_EARLY_EVENING_UTC) as domain_facade:
            restaurant_local_now: datetime = await domain_facade.get_restaurant_local_now()
            requested_start: datetime = datetime.combine(reservation_date, starts_at, tzinfo=restaurant_local_now.tzinfo)
            assert restaurant_local_now < requested_start <= restaurant_local_now + timedelta(minutes=30), (
                f"This scenario books a table that starts within half an hour of {restaurant_local_now}, but {requested_start} does not"
            )
            actual_reservation: Reservation = await domain_facade.create_reservation(
                create_reservation_request(
                    generated_guest, reservation_date=QUIET_THURSDAY, reservation_time=f"{starts_at:%H:%M}", party_size=party_size
                )
            )

        AsserterReservation.assert_new_reservation_is_as_expected(expected_new_reservation, actual_reservation)

    async def test_CreateReservation_WhenEveryFittingTableIsTaken_ThenNothingIsBookedAndOpenTimesAreOffered(
        self, restaurant_database_path: Path
    ) -> None:
        generated_guest: GeneratedGuest = create_generated_guest()
        requested_time: time = time(19, 0)
        party_size: int = 4
        expected_found_reservations: list[Reservation] = []
        expected_exception_metadata: ExpectedExceptionMetadata = ExpectedExceptionMetadata(
            http_status_code=409,
            exception_action=ExceptionAction.USER_ACTION_REQUIRED,
            reason="No table is available at the requested time",
            severity=Severity.ERROR,
            log_event=LogEventReservation.RESERVATION_SCHEDULING,
        )
        expected_contextual_data_by_name: dict[str, str | int] = {
            RESERVATION_DATE_CONTEXT_NAME: BUSY_FRIDAY,
            RESERVATION_PARTY_SIZE_CONTEXT_NAME: party_size,
        }

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            expected_alternative_times: list[time] = await derive_busy_friday_open_times(domain_facade, requested_time, party_size)
            expected_message_phrases: list[str] = [f"{expected_alternative_time:%H:%M}" for expected_alternative_time in expected_alternative_times]
            with pytest.raises(NoTableAvailableException) as raised:
                await domain_facade.create_reservation(
                    create_reservation_request(
                        generated_guest, reservation_date=BUSY_FRIDAY, reservation_time=f"{requested_time:%H:%M}", party_size=party_size
                    )
                )
            actual_found_reservations: list[Reservation] = await domain_facade.find_reservations(
                create_search_request(generated_guest.phone_digits, generated_guest.guest_name, date.fromisoformat(BUSY_FRIDAY))
            )

        AsserterException.assert_no_table_refusal_is_as_expected(
            expected_alternative_times=expected_alternative_times,
            expected_exception_content=ExpectedExceptionContent(
                message_phrases=expected_message_phrases,
                exception_metadata=expected_exception_metadata,
                contextual_data_by_name=expected_contextual_data_by_name,
            ),
            actual_no_table_available_exception=raised.value,
        )
        assert actual_found_reservations == expected_found_reservations

    async def test_CreateReservation_WhenTwoGuestsRaceForTheOnlyFittingTable_ThenExactlyOneIsBookedAndTheOtherRefused(
        self, restaurant_database_path: Path
    ) -> None:
        party_size: int = 8
        racing_guests: list[GeneratedGuest] = [create_generated_guest(), create_generated_guest()]
        fitting_table_ids: list[str] = [seeded_table.table_id for seeded_table in read_seeded_tables() if seeded_table.seats >= party_size]
        assert len(fitting_table_ids) == 1, (
            f"The race needs exactly one table to seat {party_size}; the seeded tables offer {fitting_table_ids!r}, so the seeded data "
            "no longer supports this scenario"
        )
        expected_outcome: tuple[list[str], list[type[BaseException]]] = (fitting_table_ids, [NoTableAvailableException])

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            availability_result: AvailabilityResult = await domain_facade.check_availability(
                AvailabilityRequest(reservation_date=QUIET_THURSDAY, reservation_time="19:00", party_size=party_size)
            )
            assert availability_result.is_available, (
                f"The race needs the only table for {party_size} free at 19:00 on {QUIET_THURSDAY}; the seeded data no longer supports this scenario"
            )
            racing_results: list[Reservation | BaseException] = await asyncio.gather(
                *(
                    domain_facade.create_reservation(create_reservation_request(racing_guest, party_size=party_size))
                    for racing_guest in racing_guests
                ),
                return_exceptions=True,
            )

        actual_outcome: tuple[list[str], list[type[BaseException]]] = (
            [racing_result.table_id for racing_result in racing_results if isinstance(racing_result, Reservation)],
            [type(racing_result) for racing_result in racing_results if isinstance(racing_result, BaseException)],
        )
        assert actual_outcome == expected_outcome

    async def test_CreateReservation_WhenSeveralValuesAreMissingOrMalformed_ThenEveryProblemIsReportedTogether(
        self, restaurant_database_path: Path
    ) -> None:
        expected_problem_phrases: list[str] = [
            "'guest_name' is required",
            "10-digit phone number",
            "YYYY-MM-DD",
            "is not a time",
            "'party_size' is required",
        ]
        expected_exception_metadata: ExpectedExceptionMetadata = create_validation_refusal_metadata()
        expected_contextual_data_by_name: dict[str, int] = {RESERVATION_PROBLEM_COUNT_CONTEXT_NAME: len(expected_problem_phrases)}
        invalid_reservation_request: ReservationRequest = ReservationRequest(
            guest_name=" ", phone_number="12345", party_size=None, reservation_date="next friday", reservation_time="around seven", notes=None
        )

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            with pytest.raises(ReservationRequestValidationException) as raised:
                await domain_facade.create_reservation(invalid_reservation_request)

        AsserterException.assert_validation_problems_are_as_expected(
            expected_problem_phrases=expected_problem_phrases,
            expected_exception_metadata=expected_exception_metadata,
            expected_contextual_data_by_name=expected_contextual_data_by_name,
            actual_validation_exception=raised.value,
        )

    async def test_CreateReservation_WhenTheSeatingBreaksSeveralBookingRules_ThenEveryRuleProblemIsReportedTogether(
        self, restaurant_database_path: Path
    ) -> None:
        # The request is well formed, so it is judged against the booking policy, and every policy problem is reported at once.
        expected_problem_phrases: list[str] = ["the nearest times are 19:00 and 19:15", "'party_size' must be at least 1"]
        expected_exception_metadata: ExpectedExceptionMetadata = create_policy_refusal_metadata()
        expected_contextual_data_by_name: dict[str, int] = {RESERVATION_PROBLEM_COUNT_CONTEXT_NAME: len(expected_problem_phrases)}

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            with pytest.raises(ReservationPolicyRefusedException) as raised:
                await domain_facade.create_reservation(create_reservation_request(create_generated_guest(), reservation_time="19:10", party_size=0))

        AsserterException.assert_policy_problems_are_as_expected(
            expected_problem_phrases=expected_problem_phrases,
            expected_exception_metadata=expected_exception_metadata,
            expected_contextual_data_by_name=expected_contextual_data_by_name,
            actual_reservation_policy_refused_exception=raised.value,
        )

    async def test_CreateReservation_WhenThePartyIsLargerThanCanBeBookedByPhone_ThenTheRefusalCarriesThePrivateDiningGuidance(
        self, restaurant_database_path: Path
    ) -> None:
        expected_problem_phrases: list[str] = ["private dining room"]
        expected_exception_metadata: ExpectedExceptionMetadata = create_policy_refusal_metadata()
        expected_contextual_data_by_name: dict[str, int] = {RESERVATION_PROBLEM_COUNT_CONTEXT_NAME: len(expected_problem_phrases)}

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            with pytest.raises(ReservationPolicyRefusedException) as raised:
                await domain_facade.create_reservation(create_reservation_request(create_generated_guest(), party_size=12))

        AsserterException.assert_policy_problems_are_as_expected(
            expected_problem_phrases=expected_problem_phrases,
            expected_exception_metadata=expected_exception_metadata,
            expected_contextual_data_by_name=expected_contextual_data_by_name,
            actual_reservation_policy_refused_exception=raised.value,
        )

    @pytest.mark.parametrize("booking_window_edge", ["already passed", "beyond the booking window"])
    async def test_CreateReservation_WhenTheTimeIsOutsideTheBookingWindow_ThenTheRequestIsRefused(
        self, restaurant_database_path: Path, booking_window_edge: str
    ) -> None:
        expected_exception_metadata: ExpectedExceptionMetadata = create_policy_refusal_metadata()

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            reservation_policy: ReservationPolicy = (await domain_facade.get_restaurant_profile()).reservation_policy
            restaurant_local_now: datetime = await domain_facade.get_restaurant_local_now()
            booking_window_breach: BookingWindowBreach = derive_booking_window_breach(booking_window_edge, restaurant_local_now, reservation_policy)
            expected_problem_phrases: list[str] = [booking_window_breach.expected_problem_phrase]
            expected_contextual_data_by_name: dict[str, int] = {RESERVATION_PROBLEM_COUNT_CONTEXT_NAME: len(expected_problem_phrases)}
            with pytest.raises(ReservationPolicyRefusedException) as raised:
                await domain_facade.create_reservation(
                    create_reservation_request(
                        create_generated_guest(),
                        reservation_date=f"{booking_window_breach.requested_start:%Y-%m-%d}",
                        reservation_time=f"{booking_window_breach.requested_start:%H:%M}",
                    )
                )

        AsserterException.assert_policy_problems_are_as_expected(
            expected_problem_phrases=expected_problem_phrases,
            expected_exception_metadata=expected_exception_metadata,
            expected_contextual_data_by_name=expected_contextual_data_by_name,
            actual_reservation_policy_refused_exception=raised.value,
        )


class TestFindReservations:
    async def test_FindReservations_WhenTheStoreIsCreatedTheWeekBeforeAHolidayClosure_ThenTheSeededBookingSkipsTheClosedDays(
        self, restaurant_database_path: Path
    ) -> None:
        # A seed booking lands on the next date its weekday falls on; holiday closures push it on a week at a time.
        seeded_restaurant: SeededRestaurant = read_seeded_restaurant()
        closed_dates: set[date] = {seeded_closure.closed_on for seeded_closure in seeded_restaurant.closures}
        restaurant_today: date = SUNDAY_BEFORE_CHRISTMAS_UTC.astimezone(ZoneInfo(seeded_restaurant.time_zone)).date()
        seeded_booking_guest: SeededBookingGuest = read_seeded_booking_guest(SEEDED_PRIYA_PHONE)
        first_weekday_date: date = derive_next_weekday_date(restaurant_today, Weekday(seeded_booking_guest.weekday))
        assert first_weekday_date in closed_dates, (
            f"The holiday-week scenario needs the booking's weekday to fall on a closure first, but {first_weekday_date} is open; "
            "the seeded data no longer supports this scenario"
        )
        expected_reservation_date: date = first_weekday_date
        while expected_reservation_date in closed_dates:
            expected_reservation_date += timedelta(days=7)

        expected_reservation_dates_by_searched_date: dict[date, list[date]] = {
            first_weekday_date: [],
            expected_reservation_date: [expected_reservation_date],
        }

        async with create_domain_facade(restaurant_database_path, SUNDAY_BEFORE_CHRISTMAS_UTC) as domain_facade:
            actual_reservation_dates_by_searched_date: dict[date, list[date]] = {
                searched_date: [
                    found_reservation.reservation_date
                    for found_reservation in await domain_facade.find_reservations(
                        create_search_request(SEEDED_PRIYA_PHONE, seeded_booking_guest.guest_name, searched_date)
                    )
                ]
                for searched_date in expected_reservation_dates_by_searched_date
            }

        assert actual_reservation_dates_by_searched_date == expected_reservation_dates_by_searched_date

    async def test_FindReservations_WhenThePhoneNumberIsSpokenWithSeparators_ThenTheSeededBookingIsFound(
        self, restaurant_database_path: Path
    ) -> None:
        async with create_domain_facade(restaurant_database_path) as domain_facade:
            seeded_reservation: Reservation = await retrieve_seeded_booking(domain_facade, SEEDED_PRIYA_PHONE)
            expected_found_reservations: list[Reservation] = [seeded_reservation]
            actual_found_reservations: list[Reservation] = await domain_facade.find_reservations(
                create_search_request(
                    say_phone_number_with_separators(SEEDED_PRIYA_PHONE), seeded_reservation.guest_name, seeded_reservation.reservation_date
                )
            )

        assert actual_found_reservations == expected_found_reservations

    async def test_FindReservations_WhenOnlyTheFamilyNameIsGivenInAnyCase_ThenTheSeededBookingIsFound(self, restaurant_database_path: Path) -> None:
        async with create_domain_facade(restaurant_database_path) as domain_facade:
            seeded_reservation: Reservation = await retrieve_seeded_booking(domain_facade, SEEDED_PRIYA_PHONE)
            booked_name_words: list[str] = seeded_reservation.guest_name.split()
            assert len(booked_name_words) > 1, (
                f"Finding a booking by the family name alone needs {seeded_reservation.guest_name!r} to have more than one word; "
                "the seeded data no longer supports this scenario"
            )
            expected_found_reservations: list[Reservation] = [seeded_reservation]
            actual_found_reservations: list[Reservation] = await domain_facade.find_reservations(
                create_search_request(SEEDED_PRIYA_PHONE, booked_name_words[-1].upper(), seeded_reservation.reservation_date)
            )

        assert actual_found_reservations == expected_found_reservations

    async def test_FindReservations_WhenTheNameHasSeveralLaterWords_ThenAnyOneOfThemFindsTheBooking(self, restaurant_database_path: Path) -> None:
        generated_guest: GeneratedGuest = create_generated_guest()
        # A generated note is three words, so it stands in for a name with a middle and a last name.
        booked_guest_name: str = create_generated_note()
        middle_name: str = booked_guest_name.split()[1]

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            booked_reservation: Reservation = await domain_facade.create_reservation(
                replace(create_reservation_request(generated_guest), guest_name=booked_guest_name)
            )
            expected_found_reservations: list[Reservation] = [booked_reservation]
            actual_found_reservations: list[Reservation] = await domain_facade.find_reservations(
                create_search_request(generated_guest.phone_digits, middle_name, booked_reservation.reservation_date)
            )

        assert actual_found_reservations == expected_found_reservations

    @pytest.mark.parametrize("mismatched_detail", ["given name only", "another guest's name", "another date"])
    async def test_FindReservations_WhenAnyDetailDoesNotMatchTheBooking_ThenNothingIsFound(
        self, restaurant_database_path: Path, mismatched_detail: str
    ) -> None:
        unrelated_generated_guest: GeneratedGuest = create_generated_guest()
        expected_found_reservations: list[Reservation] = []

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            seeded_reservation: Reservation = await retrieve_seeded_booking(domain_facade, SEEDED_PRIYA_PHONE)
            assert len(seeded_reservation.guest_name.split()) > 1, (
                f"The mismatch scenarios need {seeded_reservation.guest_name!r} to have a first name and a later name; "
                "the seeded data no longer supports this scenario"
            )
            searched_name: str = seeded_reservation.guest_name
            searched_date: date = seeded_reservation.reservation_date
            if mismatched_detail == "given name only":
                searched_name = seeded_reservation.guest_name.split()[0]
            elif mismatched_detail == "another guest's name":
                searched_name = unrelated_generated_guest.guest_name
            else:
                searched_date += timedelta(days=1)
            actual_found_reservations: list[Reservation] = await domain_facade.find_reservations(
                create_search_request(SEEDED_PRIYA_PHONE, searched_name, searched_date)
            )

        assert actual_found_reservations == expected_found_reservations

    async def test_FindReservations_WhenTheNameAndDateAreMissing_ThenEveryProblemIsReportedTogether(self, restaurant_database_path: Path) -> None:
        expected_problem_phrases: list[str] = ["'guest_name' is required", "'reservation_date' is required"]
        expected_exception_metadata: ExpectedExceptionMetadata = create_validation_refusal_metadata()
        expected_contextual_data_by_name: dict[str, int] = {RESERVATION_PROBLEM_COUNT_CONTEXT_NAME: len(expected_problem_phrases)}

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            with pytest.raises(ReservationRequestValidationException) as raised:
                await domain_facade.find_reservations(
                    ReservationSearchRequest(phone_number=SEEDED_PRIYA_PHONE, guest_name=None, reservation_date=" ")
                )

        AsserterException.assert_validation_problems_are_as_expected(
            expected_problem_phrases=expected_problem_phrases,
            expected_exception_metadata=expected_exception_metadata,
            expected_contextual_data_by_name=expected_contextual_data_by_name,
            actual_validation_exception=raised.value,
        )

    @pytest.mark.parametrize(
        "malformed_phone_number",
        [
            "call me",
            # Fullwidth digits look like a phone number but would be stored in a form no later search could match.
            SEEDED_PRIYA_PHONE_IN_FULLWIDTH_DIGITS,
        ],
    )
    async def test_FindReservations_WhenThePhoneNumberIsMalformed_ThenTheSearchIsRefused(
        self, restaurant_database_path: Path, malformed_phone_number: str
    ) -> None:
        seeded_booking_guest: SeededBookingGuest = read_seeded_booking_guest(SEEDED_PRIYA_PHONE)
        expected_problem_phrases: list[str] = ["must be a 10-digit phone number"]
        expected_exception_metadata: ExpectedExceptionMetadata = create_validation_refusal_metadata()
        expected_contextual_data_by_name: dict[str, int] = {RESERVATION_PROBLEM_COUNT_CONTEXT_NAME: len(expected_problem_phrases)}

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            with pytest.raises(ReservationRequestValidationException) as raised:
                await domain_facade.find_reservations(
                    create_search_request(malformed_phone_number, seeded_booking_guest.guest_name, date.fromisoformat(BUSY_FRIDAY))
                )

        AsserterException.assert_validation_problems_are_as_expected(
            expected_problem_phrases=expected_problem_phrases,
            expected_exception_metadata=expected_exception_metadata,
            expected_contextual_data_by_name=expected_contextual_data_by_name,
            actual_validation_exception=raised.value,
        )


class TestChangeReservation:
    async def test_ChangeReservation_WhenOnlyTheTimeChanges_ThenTheGuestKeepsTheirTableAndOtherDetails(self, restaurant_database_path: Path) -> None:
        busy_friday: date = date.fromisoformat(BUSY_FRIDAY)
        changed_time: time = time(20, 30)

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            current_reservation: Reservation = await retrieve_seeded_booking(domain_facade, SEEDED_PRIYA_PHONE)
            availability_result_at_changed_time: AvailabilityResult = await domain_facade.check_availability(
                AvailabilityRequest(reservation_date=BUSY_FRIDAY, reservation_time=f"{changed_time:%H:%M}", party_size=current_reservation.party_size)
            )
            assert (current_reservation.reservation_date, availability_result_at_changed_time.is_available) == (busy_friday, True), (
                f"Moving booking {current_reservation.confirmation_code} to {changed_time:%H:%M} needs it to sit on {BUSY_FRIDAY} with a table "
                f"free for its party at the new time; the seeded data no longer supports this scenario: {current_reservation!r}"
            )
            seating_duration_minutes: int = (await domain_facade.get_restaurant_profile()).reservation_policy.seating_duration_minutes
            expected_reservation: Reservation = replace(
                current_reservation,
                starts_at=changed_time,
                ends_at=(datetime.combine(busy_friday, changed_time) + timedelta(minutes=seating_duration_minutes)).time(),
            )
            actual_changed_reservation: Reservation = await domain_facade.change_reservation(
                create_change_request(current_reservation.confirmation_code, SEEDED_PRIYA_PHONE, reservation_time=f"{changed_time:%H:%M}")
            )
            actual_found_reservations: list[Reservation] = await domain_facade.find_reservations(create_booking_search_request(current_reservation))

        assert actual_changed_reservation == expected_reservation
        assert actual_found_reservations == [actual_changed_reservation]

    async def test_ChangeReservation_WhenTheCodeIsSpokenInLowercaseWithSpaces_ThenItStillIdentifiesTheBooking(
        self, restaurant_database_path: Path
    ) -> None:
        requested_notes: str = create_generated_note()

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            current_reservation: Reservation = await retrieve_unstarted_seeded_booking(
                domain_facade, SEEDED_PRIYA_PHONE, "Changing a booking by its spoken confirmation code"
            )
            confirmation_code: str = current_reservation.confirmation_code
            spoken_confirmation_code: str = f"{confirmation_code[:3].lower()} {confirmation_code[3:].lower()}"
            expected_reservation: Reservation = replace(current_reservation, notes=requested_notes)
            actual_changed_reservation: Reservation = await domain_facade.change_reservation(
                create_change_request(spoken_confirmation_code, SEEDED_PRIYA_PHONE, notes=requested_notes)
            )

        assert actual_changed_reservation == expected_reservation

    async def test_ChangeReservation_WhenTheNewTimeHasNoFittingTable_ThenTheBookingIsUnchangedAndOpenTimesAreOffered(
        self, restaurant_database_path: Path
    ) -> None:
        scenario: str = "The no-fitting-table change"
        busy_friday: date = date.fromisoformat(BUSY_FRIDAY)
        requested_time: time = time(19, 0)
        party_size: int = 4
        expected_exception_metadata: ExpectedExceptionMetadata = ExpectedExceptionMetadata(
            http_status_code=409,
            exception_action=ExceptionAction.USER_ACTION_REQUIRED,
            reason="No table is available at the requested time",
            severity=Severity.ERROR,
            log_event=LogEventReservation.RESERVATION_SCHEDULING,
        )
        expected_contextual_data_by_name: dict[str, str | int] = {
            RESERVATION_DATE_CONTEXT_NAME: BUSY_FRIDAY,
            RESERVATION_PARTY_SIZE_CONTEXT_NAME: party_size,
        }

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            current_reservation: Reservation = await retrieve_unstarted_seeded_booking(domain_facade, SEEDED_SAM_PHONE, scenario)
            availability_result_at_requested_time: AvailabilityResult = await domain_facade.check_availability(
                AvailabilityRequest(reservation_date=BUSY_FRIDAY, reservation_time=f"{requested_time:%H:%M}", party_size=party_size)
            )
            # A change keeps the booking's own table, so a booking already on that evening could keep a table that fits.
            assert (current_reservation.reservation_date != busy_friday, availability_result_at_requested_time.is_available) == (True, False), (
                f"{scenario} needs booking {current_reservation.confirmation_code} to sit on another day and no table free "
                f"for a party of {party_size} at {requested_time:%H:%M} on {BUSY_FRIDAY}; the seeded data no longer supports this scenario: "
                f"{current_reservation!r}"
            )
            expected_reservations: list[Reservation] = [current_reservation]
            expected_alternative_times: list[time] = await derive_busy_friday_open_times(domain_facade, requested_time, party_size)
            expected_message_phrases: list[str] = [f"{expected_alternative_time:%H:%M}" for expected_alternative_time in expected_alternative_times]
            with pytest.raises(NoTableAvailableException) as raised:
                await domain_facade.change_reservation(
                    create_change_request(
                        current_reservation.confirmation_code,
                        SEEDED_SAM_PHONE,
                        reservation_date=BUSY_FRIDAY,
                        reservation_time=f"{requested_time:%H:%M}",
                        party_size=party_size,
                    )
                )
            actual_found_reservations: list[Reservation] = await domain_facade.find_reservations(create_booking_search_request(current_reservation))

        AsserterException.assert_no_table_refusal_is_as_expected(
            expected_alternative_times=expected_alternative_times,
            expected_exception_content=ExpectedExceptionContent(
                message_phrases=expected_message_phrases,
                exception_metadata=expected_exception_metadata,
                contextual_data_by_name=expected_contextual_data_by_name,
            ),
            actual_no_table_available_exception=raised.value,
        )
        assert actual_found_reservations == expected_reservations

    async def test_ChangeReservation_WhenThePhoneNumberDoesNotMatch_ThenTheBookingIsNotFound(self, restaurant_database_path: Path) -> None:
        unrelated_generated_guest: GeneratedGuest = create_generated_guest()
        expected_exception_metadata: ExpectedExceptionMetadata = ExpectedExceptionMetadata(
            http_status_code=404,
            exception_action=ExceptionAction.USER_ACTION_REQUIRED,
            reason="The reservation was not found",
            severity=Severity.ERROR,
            log_event=LogEventReservation.RESERVATION_LOOKUP,
        )

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            current_reservation: Reservation = await retrieve_seeded_booking(domain_facade, SEEDED_PRIYA_PHONE)
            expected_message_phrases: list[str] = [
                "No current booking matches that confirmation code",
                "Check the code",
                "find the booking by the phone number, name and date it is booked under",
            ]
            expected_contextual_data_by_name: dict[str, str] = {CONFIRMATION_CODE_CONTEXT_NAME: current_reservation.confirmation_code}
            with pytest.raises(ReservationNotFoundException) as raised:
                await domain_facade.change_reservation(
                    create_change_request(current_reservation.confirmation_code, unrelated_generated_guest.phone_digits, reservation_time="20:30")
                )

        AsserterException.assert_message_and_metadata_are_as_expected(
            expected_exception_content=ExpectedExceptionContent(
                message_phrases=expected_message_phrases,
                exception_metadata=expected_exception_metadata,
                contextual_data_by_name=expected_contextual_data_by_name,
                withheld_message_phrases=[current_reservation.confirmation_code],
            ),
            actual_voice_agent_restaurant_exception=raised.value,
        )

    async def test_ChangeReservation_WhenTheGuestGivesThePhoneNameDateAndTimeInsteadOfTheCode_ThenTheBookingIsChanged(
        self, restaurant_database_path: Path
    ) -> None:
        changed_time: time = time(20, 30)

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            current_reservation: Reservation = await retrieve_unstarted_seeded_booking(
                domain_facade, SEEDED_PRIYA_PHONE, "Changing a booking without its confirmation code"
            )
            availability_result_at_changed_time: AvailabilityResult = await domain_facade.check_availability(
                AvailabilityRequest(
                    reservation_date=current_reservation.reservation_date.isoformat(),
                    reservation_time=f"{changed_time:%H:%M}",
                    party_size=current_reservation.party_size,
                )
            )
            assert availability_result_at_changed_time.is_available, (
                f"Moving booking {current_reservation.confirmation_code} to {changed_time:%H:%M} needs a table free for its party then; "
                "the seeded data no longer supports this scenario"
            )
            seating_duration_minutes: int = (await domain_facade.get_restaurant_profile()).reservation_policy.seating_duration_minutes
            expected_reservation: Reservation = replace(
                current_reservation,
                starts_at=changed_time,
                ends_at=(datetime.combine(current_reservation.reservation_date, changed_time) + timedelta(minutes=seating_duration_minutes)).time(),
            )
            actual_changed_reservation: Reservation = await domain_facade.change_reservation(
                create_guest_change_request(current_reservation, current_reservation.guest_name.lower(), f"{changed_time:%H:%M}")
            )

        assert actual_changed_reservation == expected_reservation

    async def test_ChangeReservation_WhenTheCodeReferenceHasNoCode_ThenTheRequestIsRefused(self, restaurant_database_path: Path) -> None:
        expected_problem_phrases: list[str] = ["'confirmation_code' is required"]
        expected_exception_metadata: ExpectedExceptionMetadata = create_validation_refusal_metadata()
        expected_contextual_data_by_name: dict[str, int] = {RESERVATION_PROBLEM_COUNT_CONTEXT_NAME: len(expected_problem_phrases)}

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            with pytest.raises(ReservationRequestValidationException) as raised:
                await domain_facade.change_reservation(create_change_request(None, None, reservation_time="20:30"))

        AsserterException.assert_validation_problems_are_as_expected(
            expected_problem_phrases=expected_problem_phrases,
            expected_exception_metadata=expected_exception_metadata,
            expected_contextual_data_by_name=expected_contextual_data_by_name,
            actual_validation_exception=raised.value,
        )

    async def test_ChangeReservation_WhenOnlySomeGuestDetailsAreGiven_ThenEachMissingDetailIsReported(self, restaurant_database_path: Path) -> None:
        expected_problem_phrases: list[str] = ["'guest_name' is required", "'booked_date' is required", "'booked_time' is required"]
        expected_exception_metadata: ExpectedExceptionMetadata = create_validation_refusal_metadata()
        expected_contextual_data_by_name: dict[str, int] = {RESERVATION_PROBLEM_COUNT_CONTEXT_NAME: len(expected_problem_phrases)}

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            with pytest.raises(ReservationRequestValidationException) as raised:
                await domain_facade.change_reservation(
                    ReservationChangeRequest(
                        booking_reference=GuestDetailsReference(phone_number=SEEDED_PRIYA_PHONE, guest_name=None, booked_date=None, booked_time=None),
                        reservation_date=None,
                        reservation_time="20:30",
                        party_size=None,
                        notes=None,
                    )
                )

        AsserterException.assert_validation_problems_are_as_expected(
            expected_problem_phrases=expected_problem_phrases,
            expected_exception_metadata=expected_exception_metadata,
            expected_contextual_data_by_name=expected_contextual_data_by_name,
            actual_validation_exception=raised.value,
        )

    async def test_ChangeReservation_WhenNothingIsAskedToChange_ThenTheRequestIsRefused(self, restaurant_database_path: Path) -> None:
        expected_problem_phrases: list[str] = ["at least one of"]
        expected_exception_metadata: ExpectedExceptionMetadata = create_validation_refusal_metadata()
        expected_contextual_data_by_name: dict[str, int] = {RESERVATION_PROBLEM_COUNT_CONTEXT_NAME: len(expected_problem_phrases)}

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            current_reservation: Reservation = await retrieve_seeded_booking(domain_facade, SEEDED_PRIYA_PHONE)
            with pytest.raises(ReservationRequestValidationException) as raised:
                await domain_facade.change_reservation(create_change_request(current_reservation.confirmation_code, SEEDED_PRIYA_PHONE))

        AsserterException.assert_validation_problems_are_as_expected(
            expected_problem_phrases=expected_problem_phrases,
            expected_exception_metadata=expected_exception_metadata,
            expected_contextual_data_by_name=expected_contextual_data_by_name,
            actual_validation_exception=raised.value,
        )

    async def test_ChangeReservation_WhenTheBookingHasAlreadyStarted_ThenItCanNoLongerBeChanged(self, restaurant_database_path: Path) -> None:
        expected_exception_metadata: ExpectedExceptionMetadata = ExpectedExceptionMetadata(
            http_status_code=409,
            exception_action=ExceptionAction.USER_ACTION_REQUIRED,
            reason="The reservation has already started",
            severity=Severity.ERROR,
            log_event=LogEventReservation.RESERVATION_SCHEDULING,
        )

        async with create_domain_facade(restaurant_database_path, FRIDAY_EVENING_UTC) as domain_facade:
            restaurant_local_now: datetime = await domain_facade.get_restaurant_local_now()
            pinned_reservation: Reservation = await retrieve_seeded_booking(domain_facade, SEEDED_PRIYA_PHONE)
            pinned_start: datetime = datetime.combine(
                pinned_reservation.reservation_date, pinned_reservation.starts_at, tzinfo=restaurant_local_now.tzinfo
            )
            assert pinned_start <= restaurant_local_now, (
                f"Booking {pinned_reservation.confirmation_code} must have started by {restaurant_local_now}; it starts at {pinned_start}"
            )
            expected_message_phrases: list[str] = ["has already started", "can no longer be changed or cancelled by phone"]
            expected_contextual_data_by_name: dict[str, str] = {
                CONFIRMATION_CODE_CONTEXT_NAME: pinned_reservation.confirmation_code,
                RESERVATION_DATE_CONTEXT_NAME: pinned_reservation.reservation_date.isoformat(),
                "Reservation.StartsAt": f"{pinned_reservation.starts_at:%H:%M}",
                "Restaurant.LocalNow": restaurant_local_now.isoformat(timespec="minutes"),
            }
            with pytest.raises(ReservationAlreadyStartedException) as raised:
                await domain_facade.change_reservation(
                    create_change_request(pinned_reservation.confirmation_code, SEEDED_PRIYA_PHONE, reservation_time="21:00")
                )

        AsserterException.assert_message_and_metadata_are_as_expected(
            expected_exception_content=ExpectedExceptionContent(
                message_phrases=expected_message_phrases,
                exception_metadata=expected_exception_metadata,
                contextual_data_by_name=expected_contextual_data_by_name,
                withheld_message_phrases=[pinned_reservation.confirmation_code],
            ),
            actual_voice_agent_restaurant_exception=raised.value,
        )


class TestCancelReservation:
    async def test_CancelReservation_WhenTheCodeAndPhoneMatch_ThenTheBookingIsCancelledAndItsTableFreed(self, restaurant_database_path: Path) -> None:
        busy_friday: date = date.fromisoformat(BUSY_FRIDAY)
        freed_seating_time: time = time(19, 0)
        freed_party_size: int = 4
        expected_found_reservations: list[Reservation] = []
        expected_availability_result: AvailabilityResult = AvailabilityResult(
            reservation_date=busy_friday, requested_time=freed_seating_time, party_size=freed_party_size, is_available=True, alternative_times=[]
        )

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            current_reservation: Reservation = await retrieve_seeded_booking(domain_facade, SEEDED_PRIYA_PHONE)
            assert (current_reservation.reservation_date, current_reservation.starts_at, current_reservation.party_size) == (
                busy_friday,
                freed_seating_time,
                freed_party_size,
            ), (
                f"Cancelling to free a table needs booking {current_reservation.confirmation_code} to hold a party of {freed_party_size} at "
                f"{freed_seating_time:%H:%M} on {BUSY_FRIDAY}; the seeded data no longer supports this scenario: {current_reservation!r}"
            )
            expected_cancelled_reservation: Reservation = replace(current_reservation, reservation_status=ReservationStatus.CANCELLED)
            actual_cancelled_reservation: Reservation = await domain_facade.cancel_reservation(
                create_code_cancellation_request(current_reservation.confirmation_code, SEEDED_PRIYA_PHONE)
            )
            actual_found_reservations: list[Reservation] = await domain_facade.find_reservations(create_booking_search_request(current_reservation))
            actual_availability_result: AvailabilityResult = await domain_facade.check_availability(
                AvailabilityRequest(reservation_date=BUSY_FRIDAY, reservation_time=f"{freed_seating_time:%H:%M}", party_size=freed_party_size)
            )

        assert actual_cancelled_reservation == expected_cancelled_reservation
        assert actual_found_reservations == expected_found_reservations
        assert actual_availability_result == expected_availability_result

    async def test_CancelReservation_WhenOnlyTheConfirmationCodeIsGiven_ThenTheBookingIsCancelled(self, restaurant_database_path: Path) -> None:
        async with create_domain_facade(restaurant_database_path) as domain_facade:
            current_reservation: Reservation = await retrieve_unstarted_seeded_booking(
                domain_facade, SEEDED_PRIYA_PHONE, "Cancelling a booking by its confirmation code alone"
            )
            expected_cancelled_reservation: Reservation = replace(current_reservation, reservation_status=ReservationStatus.CANCELLED)
            actual_cancelled_reservation: Reservation = await domain_facade.cancel_reservation(
                create_code_cancellation_request(current_reservation.confirmation_code, None)
            )

        assert actual_cancelled_reservation == expected_cancelled_reservation

    async def test_CancelReservation_WhenTheBookingIsAlreadyCancelled_ThenItIsNotFound(self, restaurant_database_path: Path) -> None:
        expected_exception_metadata: ExpectedExceptionMetadata = ExpectedExceptionMetadata(
            http_status_code=404,
            exception_action=ExceptionAction.USER_ACTION_REQUIRED,
            reason="The reservation was not found",
            severity=Severity.ERROR,
            log_event=LogEventReservation.RESERVATION_LOOKUP,
        )

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            current_reservation: Reservation = await retrieve_unstarted_seeded_booking(
                domain_facade, SEEDED_PRIYA_PHONE, "Cancelling a booking a second time"
            )
            reservation_cancellation_request: ReservationCancellationRequest = create_code_cancellation_request(
                current_reservation.confirmation_code, SEEDED_PRIYA_PHONE
            )
            expected_message_phrases: list[str] = ["No current booking matches that confirmation code", "Check the code"]
            expected_contextual_data_by_name: dict[str, str] = {CONFIRMATION_CODE_CONTEXT_NAME: current_reservation.confirmation_code}
            await domain_facade.cancel_reservation(reservation_cancellation_request)
            with pytest.raises(ReservationNotFoundException) as raised:
                await domain_facade.cancel_reservation(reservation_cancellation_request)

        AsserterException.assert_message_and_metadata_are_as_expected(
            expected_exception_content=ExpectedExceptionContent(
                message_phrases=expected_message_phrases,
                exception_metadata=expected_exception_metadata,
                contextual_data_by_name=expected_contextual_data_by_name,
                withheld_message_phrases=[current_reservation.confirmation_code],
            ),
            actual_voice_agent_restaurant_exception=raised.value,
        )

    async def test_CancelReservation_WhenTheGuestDetailsMatchWithoutTheCode_ThenTheBookingIsCancelled(self, restaurant_database_path: Path) -> None:
        async with create_domain_facade(restaurant_database_path) as domain_facade:
            current_reservation: Reservation = await retrieve_unstarted_seeded_booking(
                domain_facade, SEEDED_PRIYA_PHONE, "Cancelling a booking without its confirmation code"
            )
            expected_cancelled_reservation: Reservation = replace(current_reservation, reservation_status=ReservationStatus.CANCELLED)
            actual_cancelled_reservation: Reservation = await domain_facade.cancel_reservation(
                create_guest_cancellation_request(current_reservation, current_reservation.guest_name, f"{current_reservation.starts_at:%H:%M}")
            )

        assert actual_cancelled_reservation == expected_cancelled_reservation

    async def test_CancelReservation_WhenTheNameIsNotTheOneOnTheBooking_ThenNothingIsCancelledAndTheCodeIsNotRevealed(
        self, restaurant_database_path: Path
    ) -> None:
        unrelated_generated_guest: GeneratedGuest = create_generated_guest()
        expected_exception_metadata: ExpectedExceptionMetadata = create_guest_not_found_metadata()

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            current_reservation: Reservation = await retrieve_unstarted_seeded_booking(
                domain_facade, SEEDED_PRIYA_PHONE, "Refusing a cancellation under the wrong name"
            )
            expected_found_reservations: list[Reservation] = [current_reservation]
            expected_message_phrases: list[str] = [
                f"No current booking at {current_reservation.starts_at:%H:%M} on {current_reservation.reservation_date.isoformat()}",
                "matches that phone number and name",
            ]
            expected_contextual_data_by_name: dict[str, str | int] = {
                RESERVATION_DATE_CONTEXT_NAME: current_reservation.reservation_date.isoformat(),
                "Reservation.MatchingBookingCount": 0,
            }
            with pytest.raises(GuestReservationNotFoundException) as raised:
                await domain_facade.cancel_reservation(
                    create_guest_cancellation_request(
                        current_reservation, unrelated_generated_guest.guest_name, f"{current_reservation.starts_at:%H:%M}"
                    )
                )
            actual_found_reservations: list[Reservation] = await domain_facade.find_reservations(create_booking_search_request(current_reservation))

        AsserterException.assert_message_and_metadata_are_as_expected(
            expected_exception_content=ExpectedExceptionContent(
                message_phrases=expected_message_phrases,
                exception_metadata=expected_exception_metadata,
                contextual_data_by_name=expected_contextual_data_by_name,
                withheld_message_phrases=[current_reservation.confirmation_code],
            ),
            actual_voice_agent_restaurant_exception=raised.value,
        )
        assert actual_found_reservations == expected_found_reservations

    async def test_CancelReservation_WhenTheBookedEveningTimeIsSaidWithoutPm_ThenTheEveningBookingIsCancelled(
        self, restaurant_database_path: Path
    ) -> None:
        async with create_domain_facade(restaurant_database_path) as domain_facade:
            current_reservation: Reservation = await retrieve_unstarted_seeded_booking(
                domain_facade, SEEDED_PRIYA_PHONE, "Cancelling an evening booking whose time is said without PM"
            )
            assert current_reservation.starts_at.hour > NOON_HOUR, (
                f"Saying the booked time without PM needs booking {current_reservation.confirmation_code} to start in the evening, "
                f"but it starts at {current_reservation.starts_at:%H:%M}; the seeded data no longer supports this scenario"
            )
            spoken_booked_time: str = f"{current_reservation.starts_at.hour - NOON_HOUR}:{current_reservation.starts_at:%M}"
            expected_cancelled_reservation: Reservation = replace(current_reservation, reservation_status=ReservationStatus.CANCELLED)
            actual_cancelled_reservation: Reservation = await domain_facade.cancel_reservation(
                create_guest_cancellation_request(current_reservation, current_reservation.guest_name, spoken_booked_time)
            )

        assert actual_cancelled_reservation == expected_cancelled_reservation
