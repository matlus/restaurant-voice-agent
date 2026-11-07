# Acceptance tests for the restaurant's own information: profile, local time, opening hours, configuration.
# Black-box through the DomainFacade against a real SQLite store seeded from the bundled seed files.

from datetime import date, datetime, time
from pathlib import Path
from typing import Final

import pytest

from acceptance_support.asserters.asserter_exception import AsserterException
from acceptance_support.asserters.asserter_restaurant_profile import AsserterRestaurantProfile
from acceptance_support.generated_guests import GeneratedGuest, create_generated_guest
from acceptance_support.service_locator_testing import (
    DATABASE_PATH_VARIABLE_NAME,
    WEDNESDAY_AFTERNOON_UTC,
    ServiceLocatorTesting,
    create_domain_facade,
)
from voice_agent_restaurant import (
    ClosedWeekday,
    Closure,
    ConfigurationSettingException,
    DomainFacade,
    ExceptionAction,
    OpeningHours,
    OpenWeekday,
    Reservation,
    ReservationRequest,
    ReservationSearchRequest,
    RestaurantProfile,
    Weekday,
)

SEEDED_RESTAURANT_NAME: Final[str] = "Ember & Sprout"
SEEDED_TIME_ZONE: Final[str] = "America/Chicago"
SEEDED_SEATING_DURATION_MINUTES: Final[int] = 90
SEEDED_MAXIMUM_PARTY_SIZE: Final[int] = 8


class TestRestaurantInformation:
    async def test_GetRestaurantProfile_WhenTheStoreIsNew_ThenTheSeededProfileAndBookingPolicyAreReturned(
        self, restaurant_database_path: Path
    ) -> None:
        async with create_domain_facade(restaurant_database_path) as domain_facade:
            restaurant_profile: RestaurantProfile = await domain_facade.get_restaurant_profile()

        AsserterRestaurantProfile.assert_seeded_profile_obligations_hold(
            expected_restaurant_name=SEEDED_RESTAURANT_NAME,
            expected_time_zone=SEEDED_TIME_ZONE,
            expected_seating_duration_minutes=SEEDED_SEATING_DURATION_MINUTES,
            expected_maximum_party_size=SEEDED_MAXIMUM_PARTY_SIZE,
            expected_house_note_phrase="shared kitchen",
            actual_restaurant_profile=restaurant_profile,
        )

    async def test_GetRestaurantLocalNow_WhenTheClockIsInUtc_ThenTheTimeIsExpressedInTheRestaurantTimeZone(
        self, restaurant_database_path: Path
    ) -> None:
        expected_local_date_and_time: tuple[date, time] = (date(2026, 11, 4), time(15, 0))

        async with create_domain_facade(restaurant_database_path, WEDNESDAY_AFTERNOON_UTC) as domain_facade:
            restaurant_local_now: datetime = await domain_facade.get_restaurant_local_now()

        assert (restaurant_local_now.date(), restaurant_local_now.time()) == expected_local_date_and_time

    async def test_GetOpeningHours_WhenAsked_ThenEveryWeekdayIsListedWithMondayClosedAndOnlyUpcomingClosuresInTheBookingWindow(
        self, restaurant_database_path: Path
    ) -> None:
        # The booking window runs 60 days from 2026-11-04, so New Year's Day (2027-01-01) falls inside it.
        expected_opening_hours: OpeningHours = OpeningHours(
            weekly_hours=[
                ClosedWeekday(weekday=Weekday.MONDAY),
                OpenWeekday(weekday=Weekday.TUESDAY, opens_at=time(17, 0), closes_at=time(22, 0)),
                OpenWeekday(weekday=Weekday.WEDNESDAY, opens_at=time(17, 0), closes_at=time(22, 0)),
                OpenWeekday(weekday=Weekday.THURSDAY, opens_at=time(17, 0), closes_at=time(22, 0)),
                OpenWeekday(weekday=Weekday.FRIDAY, opens_at=time(17, 0), closes_at=time(23, 0)),
                OpenWeekday(weekday=Weekday.SATURDAY, opens_at=time(12, 0), closes_at=time(23, 0)),
                OpenWeekday(weekday=Weekday.SUNDAY, opens_at=time(11, 0), closes_at=time(21, 0)),
            ],
            upcoming_closures=[
                Closure(closed_on=date(2026, 11, 26), reason="Thanksgiving Day"),
                Closure(closed_on=date(2026, 12, 24), reason="Christmas Eve"),
                Closure(closed_on=date(2026, 12, 25), reason="Christmas Day"),
                Closure(closed_on=date(2027, 1, 1), reason="New Year's Day"),
            ],
            last_seating_minutes_before_close=SEEDED_SEATING_DURATION_MINUTES,
        )

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            opening_hours: OpeningHours = await domain_facade.get_opening_hours()

        assert opening_hours == expected_opening_hours

    async def test_FindReservations_WhenTheStoreAlreadyExists_ThenItIsReusedAndEarlierBookingsRemain(self, restaurant_database_path: Path) -> None:
        generated_guest: GeneratedGuest = create_generated_guest()
        async with create_domain_facade(restaurant_database_path) as first_domain_facade:
            created_reservation: Reservation = await first_domain_facade.create_reservation(
                ReservationRequest(
                    guest_name=generated_guest.guest_name,
                    phone_number=generated_guest.phone_digits,
                    party_size=2,
                    reservation_date="2026-11-05",
                    reservation_time="18:00",
                    notes=None,
                )
            )
        expected_reservations: list[Reservation] = [created_reservation]

        async with create_domain_facade(restaurant_database_path) as second_domain_facade:
            found_reservations: list[Reservation] = await second_domain_facade.find_reservations(
                ReservationSearchRequest(phone_number=generated_guest.phone_digits)
            )

        assert found_reservations == expected_reservations

    def test_DomainFacade_WhenTheDatabasePathSettingIsMissing_ThenConstructionFailsNamingTheSetting(self) -> None:
        with pytest.raises(ConfigurationSettingException) as raised:
            DomainFacade(ServiceLocatorTesting({DATABASE_PATH_VARIABLE_NAME: "   "}, WEDNESDAY_AFTERNOON_UTC))

        AsserterException.assert_message_status_and_action_are_as_expected(
            expected_message_phrases=[DATABASE_PATH_VARIABLE_NAME, "empty or whitespace"],
            expected_http_status_code=500,
            expected_exception_action=ExceptionAction.INFRA_ACTION_REQUIRED,
            actual_exception=raised.value,
        )

    def test_DomainFacade_WhenTheDatabasePathContainsANulCharacter_ThenConstructionFailsNamingTheSetting(self) -> None:
        unusable_database_path: str = "data/restaurant" + chr(0) + ".sqlite3"

        with pytest.raises(ConfigurationSettingException) as raised:
            DomainFacade(ServiceLocatorTesting({DATABASE_PATH_VARIABLE_NAME: unusable_database_path}, WEDNESDAY_AFTERNOON_UTC))

        AsserterException.assert_message_status_and_action_are_as_expected(
            expected_message_phrases=[DATABASE_PATH_VARIABLE_NAME, "NUL character"],
            expected_http_status_code=500,
            expected_exception_action=ExceptionAction.INFRA_ACTION_REQUIRED,
            actual_exception=raised.value,
        )
