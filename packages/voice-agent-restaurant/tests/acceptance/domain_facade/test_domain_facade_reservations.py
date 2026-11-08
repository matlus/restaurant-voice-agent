# Acceptance tests for availability and the reservation lifecycle: book, find, change, cancel.
# Black-box through the DomainFacade against a real SQLite store seeded from the bundled seed files.
#
# "Now" is Wednesday 2026-11-04 15:00 in Riverton unless a test says otherwise. The seed fills every 4-top around 19:00
# on Friday 2026-11-06, so a party of 4 cannot sit at 19:00 that evening. Tests pin a seeded booking by its phone number
# alone, read it first and derive their expectations from what they read; the open times a refusal must offer are worked
# out from the restaurant's own availability answers for every other bookable time that day.

from dataclasses import replace
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Final

import pytest

from acceptance_support.asserters.asserter_exception import AsserterException, ExpectedExceptionMetadata
from acceptance_support.asserters.asserter_reservation import AsserterReservation, ExpectedNewReservation
from acceptance_support.bundled_seed import SeededRestaurant, SeededTable, SeededWeekdayHours, read_seeded_restaurant, read_seeded_tables
from acceptance_support.generated_guests import GeneratedGuest, create_generated_guest, create_generated_note
from acceptance_support.service_locator_testing import FRIDAY_EVENING_UTC, create_domain_facade
from voice_agent_restaurant import (
    AvailabilityRequest,
    AvailabilityResult,
    Closure,
    DomainFacade,
    ExceptionAction,
    NoTableAvailableException,
    OpeningHours,
    OpenWeekday,
    OutsideSeatingHoursException,
    Reservation,
    ReservationAlreadyStartedException,
    ReservationCancellationRequest,
    ReservationChangeRequest,
    ReservationNotFoundException,
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
SEEDED_PRIYA_PHONE: Final[str] = "5550101001"
SEEDED_SAM_PHONE: Final[str] = "5550101010"
FULLWIDTH_DIGIT_ZERO_CODE_POINT: Final[int] = 0xFF10
SEEDED_PRIYA_PHONE_IN_FULLWIDTH_DIGITS: Final[str] = "".join(chr(FULLWIDTH_DIGIT_ZERO_CODE_POINT + int(digit)) for digit in SEEDED_PRIYA_PHONE)
# A refusal offers at most this many other open times, the ones nearest to the time asked for.
OFFERED_ALTERNATIVE_TIME_COUNT: Final[int] = 3
MINUTES_PER_HOUR: Final[int] = 60
RESERVATION_VALIDATION_REFUSAL_REASON: Final[str] = "Reservation request failed validation"
RESERVATION_DATE_CONTEXT_NAME: Final[str] = "Reservation.Date"
RESERVATION_PARTY_SIZE_CONTEXT_NAME: Final[str] = "Reservation.PartySize"
RESERVATION_PROBLEM_COUNT_CONTEXT_NAME: Final[str] = "Reservation.ProblemCount"
CONFIRMATION_CODE_CONTEXT_NAME: Final[str] = "Reservation.ConfirmationCode"


def create_reservation_request(
    generated_guest: GeneratedGuest,
    reservation_date: str | None = QUIET_THURSDAY,
    reservation_time: str | None = "19:00",
    party_size: int | None = 2,
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
        confirmation_code=confirmation_code,
        phone_number=phone_number,
        reservation_date=reservation_date,
        reservation_time=reservation_time,
        party_size=party_size,
        notes=notes,
    )


def create_validation_refusal_metadata() -> ExpectedExceptionMetadata:
    return ExpectedExceptionMetadata(
        http_status_code=400,
        exception_action=ExceptionAction.USER_ACTION_REQUIRED,
        reason=RESERVATION_VALIDATION_REFUSAL_REASON,
        severity=Severity.ERROR,
    )


async def read_seeded_booking(domain_facade: DomainFacade, phone_number: str) -> Reservation:
    found_reservations: list[Reservation] = await domain_facade.find_reservations(ReservationSearchRequest(phone_number=phone_number))
    assert len(found_reservations) == 1, f"The seed must hold exactly one upcoming booking for {phone_number}; found {found_reservations!r}"
    return found_reservations[0]


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


def retrieve_smallest_fitting_table_id(party_size: int) -> str:
    """The table a new booking takes when every table is free: the fewest seats that hold the party, then the lowest table id."""
    fitting_tables: list[SeededTable] = [seeded_table for seeded_table in read_seeded_tables() if seeded_table.seats >= party_size]
    assert fitting_tables, f"The seeded tables must hold a party of {party_size}; the seeded data no longer supports this scenario"
    return min(fitting_tables, key=lambda fitting_table: (fitting_table.seats, fitting_table.table_id)).table_id


def retrieve_seeded_weekday_hours(seeded_restaurant: SeededRestaurant, weekday: Weekday) -> SeededWeekdayHours:
    weekday_hours: list[SeededWeekdayHours] = [
        seeded_weekday_hours for seeded_weekday_hours in seeded_restaurant.weekly_hours if seeded_weekday_hours.weekday == weekday.value
    ]
    assert len(weekday_hours) == 1, f"The seed must list {weekday.value} exactly once; found {weekday_hours!r}"
    return weekday_hours[0]


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
                alternative_times=await derive_offered_open_times(domain_facade, busy_friday, requested_time, party_size),
            )
            actual_availability_result: AvailabilityResult = await domain_facade.check_availability(
                AvailabilityRequest(reservation_date=BUSY_FRIDAY, reservation_time=f"{requested_time:%H:%M}", party_size=party_size)
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
        )
        expected_contextual_data_by_name: dict[str, str] = {RESERVATION_DATE_CONTEXT_NAME: CLOSED_MONDAY}

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            with pytest.raises(RestaurantClosedOnDateException) as raised:
                await domain_facade.check_availability(AvailabilityRequest(reservation_date=CLOSED_MONDAY, reservation_time="19:00", party_size=2))

        AsserterException.assert_message_and_metadata_are_as_expected(
            expected_message_phrases=expected_message_phrases,
            expected_exception_metadata=expected_exception_metadata,
            expected_contextual_data_by_name=expected_contextual_data_by_name,
            actual_voice_agent_restaurant_exception=raised.value,
        )

    async def test_CheckAvailability_WhenTheDateIsAHolidayClosure_ThenTheRefusalNamesTheHoliday(self, restaurant_database_path: Path) -> None:
        expected_exception_metadata: ExpectedExceptionMetadata = ExpectedExceptionMetadata(
            http_status_code=400,
            exception_action=ExceptionAction.USER_ACTION_REQUIRED,
            reason="The restaurant is closed on the requested date",
            severity=Severity.ERROR,
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
            expected_message_phrases=expected_message_phrases,
            expected_exception_metadata=expected_exception_metadata,
            expected_contextual_data_by_name=expected_contextual_data_by_name,
            actual_voice_agent_restaurant_exception=raised.value,
        )
        assert raised.value.closure_reason == upcoming_closure.reason

    async def test_CheckAvailability_WhenTheTimeLeavesTooLittleBeforeClosing_ThenTheRefusalGivesTheSeatingHours(
        self, restaurant_database_path: Path
    ) -> None:
        # The last table is seated one full seating before closing; the request is one slot later than that.
        seeded_restaurant: SeededRestaurant = read_seeded_restaurant()
        friday_hours: SeededWeekdayHours = retrieve_seeded_weekday_hours(seeded_restaurant, Weekday.FRIDAY)
        friday_opens_at: time | None = friday_hours.opens_at
        friday_closes_at: time | None = friday_hours.closes_at
        assert friday_opens_at is not None, "The restaurant must open on Fridays for this scenario; the seeded data no longer supports it"
        assert friday_closes_at is not None, "The restaurant must close on Fridays for this scenario; the seeded data no longer supports it"
        first_seating_time: time = friday_opens_at
        last_seating_time: time = to_time(to_minutes(friday_closes_at) - seeded_restaurant.reservation_policy.seating_duration_minutes)
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
        )
        expected_contextual_data_by_name: dict[str, str] = {RESERVATION_DATE_CONTEXT_NAME: BUSY_FRIDAY}

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            with pytest.raises(OutsideSeatingHoursException) as raised:
                await domain_facade.check_availability(
                    AvailabilityRequest(reservation_date=BUSY_FRIDAY, reservation_time=requested_time, party_size=2)
                )

        AsserterException.assert_message_and_metadata_are_as_expected(
            expected_message_phrases=expected_message_phrases,
            expected_exception_metadata=expected_exception_metadata,
            expected_contextual_data_by_name=expected_contextual_data_by_name,
            actual_voice_agent_restaurant_exception=raised.value,
        )
        assert (raised.value.first_seating_time, raised.value.last_seating_time) == expected_seating_hours


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
                ReservationSearchRequest(phone_number=generated_guest.phone_number_with_country_code)
            )

        AsserterReservation.assert_new_reservation_is_as_expected(expected_new_reservation, actual_reservation)
        assert actual_found_reservations == [actual_reservation]

    async def test_CreateReservation_WhenEveryFittingTableIsTaken_ThenNothingIsBookedAndOpenTimesAreOffered(
        self, restaurant_database_path: Path
    ) -> None:
        generated_guest: GeneratedGuest = create_generated_guest()
        busy_friday: date = date.fromisoformat(BUSY_FRIDAY)
        requested_time: time = time(19, 0)
        party_size: int = 4
        expected_found_reservations: list[Reservation] = []
        expected_exception_metadata: ExpectedExceptionMetadata = ExpectedExceptionMetadata(
            http_status_code=409,
            exception_action=ExceptionAction.USER_ACTION_REQUIRED,
            reason="No table is available at the requested time",
            severity=Severity.ERROR,
        )
        expected_contextual_data_by_name: dict[str, str | int] = {
            RESERVATION_DATE_CONTEXT_NAME: BUSY_FRIDAY,
            RESERVATION_PARTY_SIZE_CONTEXT_NAME: party_size,
        }

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            expected_alternative_times: list[time] = await derive_offered_open_times(domain_facade, busy_friday, requested_time, party_size)
            with pytest.raises(NoTableAvailableException) as raised:
                await domain_facade.create_reservation(
                    create_reservation_request(
                        generated_guest, reservation_date=BUSY_FRIDAY, reservation_time=f"{requested_time:%H:%M}", party_size=party_size
                    )
                )
            actual_found_reservations: list[Reservation] = await domain_facade.find_reservations(
                ReservationSearchRequest(phone_number=generated_guest.phone_digits)
            )

        AsserterException.assert_no_table_refusal_is_as_expected(
            expected_alternative_times=expected_alternative_times,
            expected_exception_metadata=expected_exception_metadata,
            expected_contextual_data_by_name=expected_contextual_data_by_name,
            actual_no_table_available_exception=raised.value,
        )
        assert actual_found_reservations == expected_found_reservations

    async def test_CreateReservation_WhenSeveralValuesAreMissingOrMalformed_ThenEveryProblemIsReportedTogether(
        self, restaurant_database_path: Path
    ) -> None:
        expected_problem_phrases: list[str] = [
            "'guest_name' is required",
            "10-digit phone number",
            "YYYY-MM-DD",
            "HH:MM",
            "'party_size' is required",
        ]
        expected_exception_metadata: ExpectedExceptionMetadata = create_validation_refusal_metadata()
        expected_contextual_data_by_name: dict[str, int] = {RESERVATION_PROBLEM_COUNT_CONTEXT_NAME: len(expected_problem_phrases)}
        invalid_reservation_request: ReservationRequest = ReservationRequest(
            guest_name=" ", phone_number="12345", party_size=None, reservation_date="next friday", reservation_time="7 pm", notes=None
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
        expected_problem_phrases: list[str] = ["15-minute boundary", "'party_size' must be at least 1"]
        expected_exception_metadata: ExpectedExceptionMetadata = create_validation_refusal_metadata()
        expected_contextual_data_by_name: dict[str, int] = {RESERVATION_PROBLEM_COUNT_CONTEXT_NAME: len(expected_problem_phrases)}

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            with pytest.raises(ReservationRequestValidationException) as raised:
                await domain_facade.create_reservation(create_reservation_request(create_generated_guest(), reservation_time="19:10", party_size=0))

        AsserterException.assert_validation_problems_are_as_expected(
            expected_problem_phrases=expected_problem_phrases,
            expected_exception_metadata=expected_exception_metadata,
            expected_contextual_data_by_name=expected_contextual_data_by_name,
            actual_validation_exception=raised.value,
        )

    async def test_CreateReservation_WhenThePartyIsLargerThanCanBeBookedByPhone_ThenTheRefusalCarriesThePrivateDiningGuidance(
        self, restaurant_database_path: Path
    ) -> None:
        expected_problem_phrases: list[str] = ["private dining room"]
        expected_exception_metadata: ExpectedExceptionMetadata = create_validation_refusal_metadata()
        expected_contextual_data_by_name: dict[str, int] = {RESERVATION_PROBLEM_COUNT_CONTEXT_NAME: len(expected_problem_phrases)}

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            with pytest.raises(ReservationRequestValidationException) as raised:
                await domain_facade.create_reservation(create_reservation_request(create_generated_guest(), party_size=12))

        AsserterException.assert_validation_problems_are_as_expected(
            expected_problem_phrases=expected_problem_phrases,
            expected_exception_metadata=expected_exception_metadata,
            expected_contextual_data_by_name=expected_contextual_data_by_name,
            actual_validation_exception=raised.value,
        )

    @pytest.mark.parametrize(
        ("reservation_date", "reservation_time", "expected_problem_phrase"),
        [
            ("2026-11-04", "15:15", "less than 30 minutes away"),
            ("2026-11-03", "19:00", "has already passed"),
            ("2027-01-06", "19:00", "more than 60 days ahead"),
        ],
    )
    async def test_CreateReservation_WhenTheTimeIsOutsideTheBookingWindow_ThenTheRequestIsRefused(
        self, restaurant_database_path: Path, reservation_date: str, reservation_time: str, expected_problem_phrase: str
    ) -> None:
        expected_problem_phrases: list[str] = [expected_problem_phrase]
        expected_exception_metadata: ExpectedExceptionMetadata = create_validation_refusal_metadata()
        expected_contextual_data_by_name: dict[str, int] = {RESERVATION_PROBLEM_COUNT_CONTEXT_NAME: len(expected_problem_phrases)}

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            with pytest.raises(ReservationRequestValidationException) as raised:
                await domain_facade.create_reservation(
                    create_reservation_request(create_generated_guest(), reservation_date=reservation_date, reservation_time=reservation_time)
                )

        AsserterException.assert_validation_problems_are_as_expected(
            expected_problem_phrases=expected_problem_phrases,
            expected_exception_metadata=expected_exception_metadata,
            expected_contextual_data_by_name=expected_contextual_data_by_name,
            actual_validation_exception=raised.value,
        )


class TestFindReservations:
    async def test_FindReservations_WhenThePhoneNumberIsSpokenWithSeparators_ThenTheSeededBookingIsFound(
        self, restaurant_database_path: Path
    ) -> None:
        async with create_domain_facade(restaurant_database_path) as domain_facade:
            expected_found_reservations: list[Reservation] = [await read_seeded_booking(domain_facade, SEEDED_PRIYA_PHONE)]
            actual_found_reservations: list[Reservation] = await domain_facade.find_reservations(
                ReservationSearchRequest(phone_number=say_phone_number_with_separators(SEEDED_PRIYA_PHONE))
            )

        assert actual_found_reservations == expected_found_reservations

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
        expected_problem_phrases: list[str] = ["must be a 10-digit phone number"]
        expected_exception_metadata: ExpectedExceptionMetadata = create_validation_refusal_metadata()
        expected_contextual_data_by_name: dict[str, int] = {RESERVATION_PROBLEM_COUNT_CONTEXT_NAME: len(expected_problem_phrases)}

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            with pytest.raises(ReservationRequestValidationException) as raised:
                await domain_facade.find_reservations(ReservationSearchRequest(phone_number=malformed_phone_number))

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
            current_reservation: Reservation = await read_seeded_booking(domain_facade, SEEDED_PRIYA_PHONE)
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
            actual_found_reservations: list[Reservation] = await domain_facade.find_reservations(
                ReservationSearchRequest(phone_number=SEEDED_PRIYA_PHONE)
            )

        assert actual_changed_reservation == expected_reservation
        assert actual_found_reservations == [actual_changed_reservation]

    async def test_ChangeReservation_WhenTheCodeIsSpokenInLowercaseWithSpaces_ThenItStillIdentifiesTheBooking(
        self, restaurant_database_path: Path
    ) -> None:
        requested_notes: str = create_generated_note()

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            current_reservation: Reservation = await read_seeded_booking(domain_facade, SEEDED_PRIYA_PHONE)
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
        busy_friday: date = date.fromisoformat(BUSY_FRIDAY)
        requested_time: time = time(19, 0)
        party_size: int = 4
        expected_exception_metadata: ExpectedExceptionMetadata = ExpectedExceptionMetadata(
            http_status_code=409,
            exception_action=ExceptionAction.USER_ACTION_REQUIRED,
            reason="No table is available at the requested time",
            severity=Severity.ERROR,
        )
        expected_contextual_data_by_name: dict[str, str | int] = {
            RESERVATION_DATE_CONTEXT_NAME: BUSY_FRIDAY,
            RESERVATION_PARTY_SIZE_CONTEXT_NAME: party_size,
        }

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            current_reservation: Reservation = await read_seeded_booking(domain_facade, SEEDED_SAM_PHONE)
            availability_result_at_requested_time: AvailabilityResult = await domain_facade.check_availability(
                AvailabilityRequest(reservation_date=BUSY_FRIDAY, reservation_time=f"{requested_time:%H:%M}", party_size=party_size)
            )
            # A change keeps the booking's own table, so a booking already on that evening could keep a table that fits.
            assert (current_reservation.reservation_date != busy_friday, availability_result_at_requested_time.is_available) == (True, False), (
                f"The no-fitting-table change needs booking {current_reservation.confirmation_code} to sit on another day and no table free "
                f"for a party of {party_size} at {requested_time:%H:%M} on {BUSY_FRIDAY}; the seeded data no longer supports this scenario: "
                f"{current_reservation!r}"
            )
            expected_reservations: list[Reservation] = [current_reservation]
            expected_alternative_times: list[time] = await derive_offered_open_times(domain_facade, busy_friday, requested_time, party_size)
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
            actual_found_reservations: list[Reservation] = await domain_facade.find_reservations(
                ReservationSearchRequest(phone_number=SEEDED_SAM_PHONE)
            )

        AsserterException.assert_no_table_refusal_is_as_expected(
            expected_alternative_times=expected_alternative_times,
            expected_exception_metadata=expected_exception_metadata,
            expected_contextual_data_by_name=expected_contextual_data_by_name,
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
        )

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            current_reservation: Reservation = await read_seeded_booking(domain_facade, SEEDED_PRIYA_PHONE)
            expected_message_phrases: list[str] = [
                current_reservation.confirmation_code,
                "and that phone number",
                "look the reservation up by phone number",
            ]
            expected_contextual_data_by_name: dict[str, str] = {CONFIRMATION_CODE_CONTEXT_NAME: current_reservation.confirmation_code}
            with pytest.raises(ReservationNotFoundException) as raised:
                await domain_facade.change_reservation(
                    create_change_request(current_reservation.confirmation_code, unrelated_generated_guest.phone_digits, reservation_time="20:30")
                )

        AsserterException.assert_message_and_metadata_are_as_expected(
            expected_message_phrases=expected_message_phrases,
            expected_exception_metadata=expected_exception_metadata,
            expected_contextual_data_by_name=expected_contextual_data_by_name,
            actual_voice_agent_restaurant_exception=raised.value,
        )

    async def test_ChangeReservation_WhenNothingIsAskedToChange_ThenTheRequestIsRefused(self, restaurant_database_path: Path) -> None:
        expected_problem_phrases: list[str] = ["at least one of"]
        expected_exception_metadata: ExpectedExceptionMetadata = create_validation_refusal_metadata()
        expected_contextual_data_by_name: dict[str, int] = {RESERVATION_PROBLEM_COUNT_CONTEXT_NAME: len(expected_problem_phrases)}

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            current_reservation: Reservation = await read_seeded_booking(domain_facade, SEEDED_PRIYA_PHONE)
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
        )

        async with create_domain_facade(restaurant_database_path, FRIDAY_EVENING_UTC) as domain_facade:
            restaurant_local_now: datetime = await domain_facade.get_restaurant_local_now()
            pinned_reservation: Reservation = await read_seeded_booking(domain_facade, SEEDED_PRIYA_PHONE)
            pinned_start: datetime = datetime.combine(
                pinned_reservation.reservation_date, pinned_reservation.starts_at, tzinfo=restaurant_local_now.tzinfo
            )
            assert pinned_start <= restaurant_local_now, (
                f"Booking {pinned_reservation.confirmation_code} must have started by {restaurant_local_now}; it starts at {pinned_start}"
            )
            expected_message_phrases: list[str] = [
                pinned_reservation.confirmation_code,
                "has already started",
                "can no longer be changed or cancelled by phone",
            ]
            expected_contextual_data_by_name: dict[str, str] = {CONFIRMATION_CODE_CONTEXT_NAME: pinned_reservation.confirmation_code}
            with pytest.raises(ReservationAlreadyStartedException) as raised:
                await domain_facade.change_reservation(
                    create_change_request(pinned_reservation.confirmation_code, SEEDED_PRIYA_PHONE, reservation_time="21:00")
                )

        AsserterException.assert_message_and_metadata_are_as_expected(
            expected_message_phrases=expected_message_phrases,
            expected_exception_metadata=expected_exception_metadata,
            expected_contextual_data_by_name=expected_contextual_data_by_name,
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
            current_reservation: Reservation = await read_seeded_booking(domain_facade, SEEDED_PRIYA_PHONE)
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
                ReservationCancellationRequest(confirmation_code=current_reservation.confirmation_code, phone_number=SEEDED_PRIYA_PHONE)
            )
            actual_found_reservations: list[Reservation] = await domain_facade.find_reservations(
                ReservationSearchRequest(phone_number=SEEDED_PRIYA_PHONE)
            )
            actual_availability_result: AvailabilityResult = await domain_facade.check_availability(
                AvailabilityRequest(reservation_date=BUSY_FRIDAY, reservation_time=f"{freed_seating_time:%H:%M}", party_size=freed_party_size)
            )

        assert actual_cancelled_reservation == expected_cancelled_reservation
        assert actual_found_reservations == expected_found_reservations
        assert actual_availability_result == expected_availability_result

    async def test_CancelReservation_WhenTheBookingIsAlreadyCancelled_ThenItIsNotFound(self, restaurant_database_path: Path) -> None:
        expected_exception_metadata: ExpectedExceptionMetadata = ExpectedExceptionMetadata(
            http_status_code=404,
            exception_action=ExceptionAction.USER_ACTION_REQUIRED,
            reason="The reservation was not found",
            severity=Severity.ERROR,
        )

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            current_reservation: Reservation = await read_seeded_booking(domain_facade, SEEDED_PRIYA_PHONE)
            reservation_cancellation_request: ReservationCancellationRequest = ReservationCancellationRequest(
                confirmation_code=current_reservation.confirmation_code, phone_number=SEEDED_PRIYA_PHONE
            )
            expected_message_phrases: list[str] = [current_reservation.confirmation_code, "and that phone number"]
            expected_contextual_data_by_name: dict[str, str] = {CONFIRMATION_CODE_CONTEXT_NAME: current_reservation.confirmation_code}
            await domain_facade.cancel_reservation(reservation_cancellation_request)
            with pytest.raises(ReservationNotFoundException) as raised:
                await domain_facade.cancel_reservation(reservation_cancellation_request)

        AsserterException.assert_message_and_metadata_are_as_expected(
            expected_message_phrases=expected_message_phrases,
            expected_exception_metadata=expected_exception_metadata,
            expected_contextual_data_by_name=expected_contextual_data_by_name,
            actual_voice_agent_restaurant_exception=raised.value,
        )
