# Acceptance tests for availability and the reservation lifecycle: book, find, change, cancel.
# Black-box through the DomainFacade against a real SQLite store seeded from the bundled seed files.
#
# "Now" is Wednesday 2026-11-04 15:00 in Riverton unless a test says otherwise. The seed fills every
# 4-top around 19:00 on Friday 2026-11-06, so a party of 4 cannot sit at 19:00 that evening. The
# nearest open times for that party are 17:45, 18:00 (the 8-top, free until 19:30) and 20:00.
# Tests that change a seeded booking read it first and derive their expectations from what they read.

from dataclasses import replace
from datetime import date, datetime, time
from pathlib import Path
from typing import Final

import pytest

from acceptance_support.asserters.asserter_exception import AsserterException
from acceptance_support.asserters.asserter_reservation import AsserterReservation, ExpectedNewReservation
from acceptance_support.generated_guests import GeneratedGuest, create_generated_guest
from acceptance_support.service_locator_testing import FRIDAY_EVENING_UTC, create_domain_facade
from voice_agent_restaurant import (
    AvailabilityRequest,
    AvailabilityResult,
    Closure,
    DomainFacade,
    ExceptionAction,
    NoTableAvailableException,
    OpeningHours,
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
)

BUSY_FRIDAY: Final[str] = "2026-11-06"
QUIET_THURSDAY: Final[str] = "2026-11-05"
CLOSED_MONDAY: Final[str] = "2026-11-09"
SEEDED_PRIYA_CODE: Final[str] = "KX4TPA"
SEEDED_PRIYA_PHONE: Final[str] = "5550101001"
SEEDED_SAM_CODE: Final[str] = "YT9WHN"
SEEDED_SAM_PHONE: Final[str] = "5550101010"
FRIDAY_FOUR_TOP_ALTERNATIVES: Final[list[time]] = [time(17, 45), time(18, 0), time(20, 0)]
FULLWIDTH_DIGIT_ZERO_CODE_POINT: Final[int] = 0xFF10
SEEDED_PRIYA_PHONE_IN_FULLWIDTH_DIGITS: Final[str] = "".join(chr(FULLWIDTH_DIGIT_ZERO_CODE_POINT + int(digit)) for digit in SEEDED_PRIYA_PHONE)


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
    confirmation_code: str | None = SEEDED_PRIYA_CODE,
    phone_number: str | None = SEEDED_PRIYA_PHONE,
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


async def read_seeded_booking(domain_facade: DomainFacade, phone_number: str) -> Reservation:
    found_reservations: list[Reservation] = await domain_facade.find_reservations(ReservationSearchRequest(phone_number=phone_number))
    assert len(found_reservations) == 1, f"The seed must hold exactly one upcoming booking for {phone_number}; found {found_reservations!r}"
    return found_reservations[0]


class TestCheckAvailability:
    async def test_CheckAvailability_WhenASmallerTableIsFree_ThenTheTimeIsAvailableWithNoAlternatives(self, restaurant_database_path: Path) -> None:
        expected_availability_result: AvailabilityResult = AvailabilityResult(
            reservation_date=date(2026, 11, 6), requested_time=time(19, 0), party_size=2, is_available=True, alternative_times=[]
        )

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            availability_result: AvailabilityResult = await domain_facade.check_availability(
                AvailabilityRequest(reservation_date=BUSY_FRIDAY, reservation_time="19:00", party_size=2)
            )

        assert availability_result == expected_availability_result

    async def test_CheckAvailability_WhenEveryFittingTableIsTaken_ThenTheThreeNearestOpenTimesAreOffered(
        self, restaurant_database_path: Path
    ) -> None:
        expected_availability_result: AvailabilityResult = AvailabilityResult(
            reservation_date=date(2026, 11, 6),
            requested_time=time(19, 0),
            party_size=4,
            is_available=False,
            alternative_times=FRIDAY_FOUR_TOP_ALTERNATIVES,
        )

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            availability_result: AvailabilityResult = await domain_facade.check_availability(
                AvailabilityRequest(reservation_date=BUSY_FRIDAY, reservation_time="19:00", party_size=4)
            )

        assert availability_result == expected_availability_result

    async def test_CheckAvailability_WhenTheRestaurantDoesNotOpenThatWeekday_ThenTheRefusalSaysItIsClosed(
        self, restaurant_database_path: Path
    ) -> None:
        async with create_domain_facade(restaurant_database_path) as domain_facade:
            with pytest.raises(RestaurantClosedOnDateException) as raised:
                await domain_facade.check_availability(AvailabilityRequest(reservation_date=CLOSED_MONDAY, reservation_time="19:00", party_size=2))

        AsserterException.assert_message_status_and_action_are_as_expected(
            expected_message_phrases=[CLOSED_MONDAY, "closed on Mondays"],
            expected_http_status_code=400,
            expected_exception_action=ExceptionAction.USER_ACTION_REQUIRED,
            actual_exception=raised.value,
        )

    async def test_CheckAvailability_WhenTheDateIsAHolidayClosure_ThenTheRefusalNamesTheHoliday(self, restaurant_database_path: Path) -> None:
        async with create_domain_facade(restaurant_database_path) as domain_facade:
            opening_hours: OpeningHours = await domain_facade.get_opening_hours()
            upcoming_closure: Closure = opening_hours.upcoming_closures[0]
            with pytest.raises(RestaurantClosedOnDateException) as raised:
                await domain_facade.check_availability(
                    AvailabilityRequest(reservation_date=upcoming_closure.closed_on.isoformat(), reservation_time="19:00", party_size=2)
                )

        assert raised.value.closure_reason == upcoming_closure.reason

    async def test_CheckAvailability_WhenTheTimeLeavesTooLittleBeforeClosing_ThenTheRefusalGivesTheSeatingHours(
        self, restaurant_database_path: Path
    ) -> None:
        # Friday closes at 23:00 and a seating lasts 90 minutes, so the last table is seated at 21:30.
        expected_seating_hours: tuple[time, time] = (time(17, 0), time(21, 30))

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            with pytest.raises(OutsideSeatingHoursException) as raised:
                await domain_facade.check_availability(AvailabilityRequest(reservation_date=BUSY_FRIDAY, reservation_time="21:45", party_size=2))

        assert (raised.value.first_seating_time, raised.value.last_seating_time) == expected_seating_hours


class TestCreateReservation:
    async def test_CreateReservation_WhenATableIsFree_ThenTheSmallestFittingTableIsBookedAndCanBeFoundByPhone(
        self, restaurant_database_path: Path
    ) -> None:
        generated_guest: GeneratedGuest = create_generated_guest()
        expected_new_reservation: ExpectedNewReservation = ExpectedNewReservation(
            guest_name=generated_guest.guest_name,
            phone_number=generated_guest.phone_digits,
            party_size=2,
            reservation_date=date(2026, 11, 5),
            starts_at=time(19, 0),
            ends_at=time(20, 30),
            table_id="T01",
            notes="Window seat please",
            reservation_status=ReservationStatus.BOOKED,
        )

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            reservation: Reservation = await domain_facade.create_reservation(
                create_reservation_request(generated_guest, notes="  Window seat please ")
            )
            found_reservations: list[Reservation] = await domain_facade.find_reservations(
                ReservationSearchRequest(phone_number=generated_guest.phone_number_with_country_code)
            )

        AsserterReservation.assert_new_reservation_is_as_expected(expected_new_reservation, reservation)
        assert found_reservations == [reservation]

    async def test_CreateReservation_WhenEveryFittingTableIsTaken_ThenNothingIsBookedAndOpenTimesAreOffered(
        self, restaurant_database_path: Path
    ) -> None:
        generated_guest: GeneratedGuest = create_generated_guest()
        expected_found_reservations: list[Reservation] = []

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            with pytest.raises(NoTableAvailableException) as raised:
                await domain_facade.create_reservation(create_reservation_request(generated_guest, reservation_date=BUSY_FRIDAY, party_size=4))
            found_reservations: list[Reservation] = await domain_facade.find_reservations(
                ReservationSearchRequest(phone_number=generated_guest.phone_digits)
            )

        AsserterException.assert_no_table_refusal_is_as_expected(
            expected_alternative_times=FRIDAY_FOUR_TOP_ALTERNATIVES, actual_exception=raised.value
        )
        assert found_reservations == expected_found_reservations

    async def test_CreateReservation_WhenSeveralValuesAreWrong_ThenEveryProblemIsReportedTogether(self, restaurant_database_path: Path) -> None:
        expected_problem_phrases: list[str] = [
            "'guest_name' is required",
            "10-digit phone number",
            "YYYY-MM-DD",
            "15-minute boundary",
            "'party_size' must be at least 1",
        ]
        invalid_reservation_request: ReservationRequest = ReservationRequest(
            guest_name=" ", phone_number="12345", party_size=0, reservation_date="next friday", reservation_time="19:10", notes=None
        )

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            with pytest.raises(ReservationRequestValidationException) as raised:
                await domain_facade.create_reservation(invalid_reservation_request)

        AsserterException.assert_validation_problems_are_as_expected(expected_problem_phrases=expected_problem_phrases, actual_exception=raised.value)

    async def test_CreateReservation_WhenThePartyIsLargerThanCanBeBookedByPhone_ThenTheRefusalCarriesThePrivateDiningGuidance(
        self, restaurant_database_path: Path
    ) -> None:
        expected_problem_phrases: list[str] = ["private dining room"]

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            with pytest.raises(ReservationRequestValidationException) as raised:
                await domain_facade.create_reservation(create_reservation_request(create_generated_guest(), party_size=12))

        AsserterException.assert_validation_problems_are_as_expected(expected_problem_phrases=expected_problem_phrases, actual_exception=raised.value)

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
        async with create_domain_facade(restaurant_database_path) as domain_facade:
            with pytest.raises(ReservationRequestValidationException) as raised:
                await domain_facade.create_reservation(
                    create_reservation_request(create_generated_guest(), reservation_date=reservation_date, reservation_time=reservation_time)
                )

        AsserterException.assert_validation_problems_are_as_expected(
            expected_problem_phrases=[expected_problem_phrase], actual_exception=raised.value
        )


class TestFindReservations:
    async def test_FindReservations_WhenThePhoneNumberIsSpokenWithSeparators_ThenTheSeededBookingIsFound(
        self, restaurant_database_path: Path
    ) -> None:
        async with create_domain_facade(restaurant_database_path) as domain_facade:
            expected_reservations: list[Reservation] = [await read_seeded_booking(domain_facade, SEEDED_PRIYA_PHONE)]
            found_reservations: list[Reservation] = await domain_facade.find_reservations(ReservationSearchRequest(phone_number="(555) 010-1001"))

        assert found_reservations == expected_reservations

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

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            with pytest.raises(ReservationRequestValidationException) as raised:
                await domain_facade.find_reservations(ReservationSearchRequest(phone_number=malformed_phone_number))

        AsserterException.assert_validation_problems_are_as_expected(expected_problem_phrases=expected_problem_phrases, actual_exception=raised.value)


class TestChangeReservation:
    async def test_ChangeReservation_WhenOnlyTheTimeChanges_ThenTheGuestKeepsTheirTableAndOtherDetails(self, restaurant_database_path: Path) -> None:
        async with create_domain_facade(restaurant_database_path) as domain_facade:
            current_reservation: Reservation = await read_seeded_booking(domain_facade, SEEDED_PRIYA_PHONE)
            expected_reservation: Reservation = replace(current_reservation, starts_at=time(20, 30), ends_at=time(22, 0))
            changed_reservation: Reservation = await domain_facade.change_reservation(create_change_request(reservation_time="20:30"))
            found_reservations: list[Reservation] = await domain_facade.find_reservations(ReservationSearchRequest(phone_number=SEEDED_PRIYA_PHONE))

        assert changed_reservation == expected_reservation
        assert found_reservations == [changed_reservation]

    async def test_ChangeReservation_WhenTheCodeIsSpokenInLowercaseWithSpaces_ThenItStillIdentifiesTheBooking(
        self, restaurant_database_path: Path
    ) -> None:
        requested_notes: str = "Anniversary, quiet corner"

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            current_reservation: Reservation = await read_seeded_booking(domain_facade, SEEDED_PRIYA_PHONE)
            expected_reservation: Reservation = replace(current_reservation, notes=requested_notes)
            changed_reservation: Reservation = await domain_facade.change_reservation(
                create_change_request(confirmation_code="kx4 tpa", notes=requested_notes)
            )

        assert changed_reservation == expected_reservation

    async def test_ChangeReservation_WhenTheNewTimeHasNoFittingTable_ThenTheBookingIsUnchangedAndOpenTimesAreOffered(
        self, restaurant_database_path: Path
    ) -> None:
        async with create_domain_facade(restaurant_database_path) as domain_facade:
            expected_reservations: list[Reservation] = [await read_seeded_booking(domain_facade, SEEDED_SAM_PHONE)]
            with pytest.raises(NoTableAvailableException) as raised:
                await domain_facade.change_reservation(
                    create_change_request(
                        confirmation_code=SEEDED_SAM_CODE,
                        phone_number=SEEDED_SAM_PHONE,
                        reservation_date=BUSY_FRIDAY,
                        reservation_time="19:00",
                        party_size=4,
                    )
                )
            found_reservations: list[Reservation] = await domain_facade.find_reservations(ReservationSearchRequest(phone_number=SEEDED_SAM_PHONE))

        AsserterException.assert_no_table_refusal_is_as_expected(
            expected_alternative_times=FRIDAY_FOUR_TOP_ALTERNATIVES, actual_exception=raised.value
        )
        assert found_reservations == expected_reservations

    async def test_ChangeReservation_WhenThePhoneNumberDoesNotMatch_ThenTheBookingIsNotFound(self, restaurant_database_path: Path) -> None:
        async with create_domain_facade(restaurant_database_path) as domain_facade:
            with pytest.raises(ReservationNotFoundException) as raised:
                await domain_facade.change_reservation(create_change_request(phone_number="5550109999", reservation_time="20:30"))

        AsserterException.assert_message_status_and_action_are_as_expected(
            expected_message_phrases=[SEEDED_PRIYA_CODE, "and that phone number", "look the reservation up by phone number"],
            expected_http_status_code=404,
            expected_exception_action=ExceptionAction.USER_ACTION_REQUIRED,
            actual_exception=raised.value,
        )

    async def test_ChangeReservation_WhenNothingIsAskedToChange_ThenTheRequestIsRefused(self, restaurant_database_path: Path) -> None:
        expected_problem_phrases: list[str] = ["at least one of"]

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            with pytest.raises(ReservationRequestValidationException) as raised:
                await domain_facade.change_reservation(create_change_request())

        AsserterException.assert_validation_problems_are_as_expected(expected_problem_phrases=expected_problem_phrases, actual_exception=raised.value)

    async def test_ChangeReservation_WhenTheBookingHasAlreadyStarted_ThenItCanNoLongerBeChanged(self, restaurant_database_path: Path) -> None:
        async with create_domain_facade(restaurant_database_path, FRIDAY_EVENING_UTC) as domain_facade:
            restaurant_local_now: datetime = await domain_facade.get_restaurant_local_now()
            pinned_reservation: Reservation = await read_seeded_booking(domain_facade, SEEDED_PRIYA_PHONE)
            pinned_start: datetime = datetime.combine(
                pinned_reservation.reservation_date, pinned_reservation.starts_at, tzinfo=restaurant_local_now.tzinfo
            )
            assert pinned_start <= restaurant_local_now, (
                f"Booking {SEEDED_PRIYA_CODE} must have started by {restaurant_local_now}; it starts at {pinned_start}"
            )
            with pytest.raises(ReservationAlreadyStartedException) as raised:
                await domain_facade.change_reservation(create_change_request(reservation_time="21:00"))

        AsserterException.assert_message_status_and_action_are_as_expected(
            expected_message_phrases=[SEEDED_PRIYA_CODE, "has already started", "can no longer be changed or cancelled by phone"],
            expected_http_status_code=409,
            expected_exception_action=ExceptionAction.USER_ACTION_REQUIRED,
            actual_exception=raised.value,
        )


class TestCancelReservation:
    async def test_CancelReservation_WhenTheCodeAndPhoneMatch_ThenTheBookingIsCancelledAndItsTableFreed(self, restaurant_database_path: Path) -> None:
        expected_found_reservations: list[Reservation] = []
        expected_availability_result: AvailabilityResult = AvailabilityResult(
            reservation_date=date(2026, 11, 6), requested_time=time(19, 0), party_size=4, is_available=True, alternative_times=[]
        )

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            current_reservation: Reservation = await read_seeded_booking(domain_facade, SEEDED_PRIYA_PHONE)
            expected_cancelled_reservation: Reservation = replace(current_reservation, reservation_status=ReservationStatus.CANCELLED)
            cancelled_reservation: Reservation = await domain_facade.cancel_reservation(
                ReservationCancellationRequest(confirmation_code=SEEDED_PRIYA_CODE, phone_number=SEEDED_PRIYA_PHONE)
            )
            found_reservations: list[Reservation] = await domain_facade.find_reservations(ReservationSearchRequest(phone_number=SEEDED_PRIYA_PHONE))
            availability_result: AvailabilityResult = await domain_facade.check_availability(
                AvailabilityRequest(reservation_date=BUSY_FRIDAY, reservation_time="19:00", party_size=4)
            )

        assert cancelled_reservation == expected_cancelled_reservation
        assert found_reservations == expected_found_reservations
        assert availability_result == expected_availability_result

    async def test_CancelReservation_WhenTheBookingIsAlreadyCancelled_ThenItIsNotFound(self, restaurant_database_path: Path) -> None:
        cancellation_request: ReservationCancellationRequest = ReservationCancellationRequest(
            confirmation_code=SEEDED_PRIYA_CODE, phone_number=SEEDED_PRIYA_PHONE
        )
        async with create_domain_facade(restaurant_database_path) as domain_facade:
            await domain_facade.cancel_reservation(cancellation_request)
            with pytest.raises(ReservationNotFoundException) as raised:
                await domain_facade.cancel_reservation(cancellation_request)

        AsserterException.assert_message_status_and_action_are_as_expected(
            expected_message_phrases=[SEEDED_PRIYA_CODE, "and that phone number"],
            expected_http_status_code=404,
            expected_exception_action=ExceptionAction.USER_ACTION_REQUIRED,
            actual_exception=raised.value,
        )
