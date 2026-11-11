# Acceptance tests for the restaurant's own information: profile, local time, opening hours, configuration.
# Black-box through the DomainFacade against a real SQLite store seeded from the bundled seed files. The facade's
# answers here are the seeded values themselves, so the expectations are read from the bundled seed file.

import sqlite3
from contextlib import closing
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Final
from zoneinfo import ZoneInfo

import pytest

from acceptance_support.asserters.asserter_exception import AsserterException, ExpectedExceptionContent, ExpectedExceptionMetadata
from acceptance_support.asserters.asserter_restaurant_profile import AsserterRestaurantProfile
from acceptance_support.bundled_seed import SeededClosedWeekday, SeededRestaurant, SeededWeekdayHours, read_seeded_restaurant
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
    LogEventConfiguration,
    LogEventRestaurantStore,
    OpeningHours,
    OpenWeekday,
    Reservation,
    ReservationRequest,
    ReservationSearchRequest,
    RestaurantProfile,
    RestaurantStoreContractViolationException,
    Severity,
    Weekday,
    WeekdayHours,
)

ENVIRONMENT_VARIABLE_NAME_CONTEXT_NAME: Final[str] = "Configuration.EnvironmentVariableName"

OLDER_STORE_VERSION: Final[int] = 1
# Monday 2026-11-30 at 15:00 in Riverton: after Thanksgiving, the first seeded closure.
AFTER_THE_FIRST_CLOSURE_UTC: Final[datetime] = datetime(2026, 11, 30, 21, 0, tzinfo=UTC)


@pytest.fixture
def older_store_database_path(restaurant_database_path: Path) -> Path:
    with closing(sqlite3.connect(restaurant_database_path)) as connection:
        # SQLite PRAGMA statements take no bound parameters, so the version is interpolated; it is a test constant, never input.
        connection.execute(f"PRAGMA user_version = {OLDER_STORE_VERSION}")
    return restaurant_database_path


@pytest.fixture
def foreign_file_database_path(restaurant_database_path: Path) -> Path:
    # The configured path holds some other file, so retrying can never help.
    restaurant_database_path.write_text("This file is not a SQLite database.\n" * 32, encoding="utf-8")
    return restaurant_database_path


def to_weekday_hours(seeded_weekday_hours: SeededWeekdayHours) -> WeekdayHours:
    weekday: Weekday = Weekday(seeded_weekday_hours.weekday)
    if isinstance(seeded_weekday_hours, SeededClosedWeekday):
        return ClosedWeekday(weekday=weekday)
    return OpenWeekday(weekday=weekday, opens_at=seeded_weekday_hours.opens_at, closes_at=seeded_weekday_hours.closes_at)


def create_configuration_refusal_metadata() -> ExpectedExceptionMetadata:
    return ExpectedExceptionMetadata(
        http_status_code=500,
        exception_action=ExceptionAction.INFRA_ACTION_REQUIRED,
        reason="Configuration settings are not set up correctly",
        severity=Severity.ERROR,
        log_event=LogEventConfiguration.RESTAURANT_STORE_SETTINGS_RETRIEVAL,
    )


class TestRestaurantInformation:
    async def test_GetRestaurantProfile_WhenTheStoreIsNew_ThenTheSeededProfileAndBookingPolicyAreReturned(
        self, restaurant_database_path: Path
    ) -> None:
        seeded_restaurant: SeededRestaurant = read_seeded_restaurant()

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            actual_restaurant_profile: RestaurantProfile = await domain_facade.get_restaurant_profile()

        AsserterRestaurantProfile.assert_seeded_profile_obligations_hold(
            expected_restaurant_name=seeded_restaurant.name,
            expected_time_zone=seeded_restaurant.time_zone,
            expected_seating_duration_minutes=seeded_restaurant.reservation_policy.seating_duration_minutes,
            expected_maximum_party_size=seeded_restaurant.reservation_policy.maximum_party_size,
            expected_allergen_notice=seeded_restaurant.allergen_notice,
            expected_house_notes=seeded_restaurant.house_notes,
            actual_restaurant_profile=actual_restaurant_profile,
        )

    async def test_GetRestaurantLocalNow_WhenTheClockIsInUtc_ThenTheTimeIsExpressedInTheRestaurantTimeZone(
        self, restaurant_database_path: Path
    ) -> None:
        seeded_restaurant: SeededRestaurant = read_seeded_restaurant()
        expected_restaurant_local_now: datetime = WEDNESDAY_AFTERNOON_UTC.astimezone(ZoneInfo(seeded_restaurant.time_zone))
        expected_local_date_and_time: tuple[date, time] = (expected_restaurant_local_now.date(), expected_restaurant_local_now.time())

        async with create_domain_facade(restaurant_database_path, WEDNESDAY_AFTERNOON_UTC) as domain_facade:
            actual_restaurant_local_now: datetime = await domain_facade.get_restaurant_local_now()

        assert (actual_restaurant_local_now.date(), actual_restaurant_local_now.time()) == expected_local_date_and_time

    async def test_GetOpeningHours_WhenAsked_ThenEveryWeekdayIsListedAndOnlyTheClosuresInsideTheBookingWindow(
        self, restaurant_database_path: Path
    ) -> None:
        # Today falls after the first seeded closure, so the window must leave a closure out as well as keep the later ones.
        seeded_restaurant: SeededRestaurant = read_seeded_restaurant()
        restaurant_today: date = AFTER_THE_FIRST_CLOSURE_UTC.astimezone(ZoneInfo(seeded_restaurant.time_zone)).date()
        last_bookable_date: date = restaurant_today + timedelta(days=seeded_restaurant.reservation_policy.booking_window_days)
        seeded_closures: list[Closure] = [
            Closure(closed_on=seeded_closure.closed_on, reason=seeded_closure.reason) for seeded_closure in seeded_restaurant.closures
        ]
        closures_inside_the_window: list[Closure] = [
            seeded_closure for seeded_closure in seeded_closures if restaurant_today <= seeded_closure.closed_on <= last_bookable_date
        ]
        assert 0 < len(closures_inside_the_window) < len(seeded_closures), (
            f"The booking window from {restaurant_today} to {last_bookable_date} must hold some seeded closures and leave others out; "
            f"the seeded data no longer supports this scenario: {seeded_closures!r}"
        )
        expected_opening_hours: OpeningHours = OpeningHours(
            weekly_hours=sorted(
                (to_weekday_hours(seeded_weekday_hours) for seeded_weekday_hours in seeded_restaurant.weekly_hours),
                key=lambda weekday_hours: list(Weekday).index(weekday_hours.weekday),
            ),
            upcoming_closures=sorted(closures_inside_the_window, key=lambda upcoming_closure: upcoming_closure.closed_on),
            last_seating_minutes_before_close=seeded_restaurant.reservation_policy.seating_duration_minutes,
        )

        async with create_domain_facade(restaurant_database_path, AFTER_THE_FIRST_CLOSURE_UTC) as domain_facade:
            actual_opening_hours: OpeningHours = await domain_facade.get_opening_hours()

        assert actual_opening_hours == expected_opening_hours

    async def test_FindReservations_WhenTheStoreAlreadyExists_ThenItIsReusedAndEarlierBookingsRemain(self, restaurant_database_path: Path) -> None:
        generated_guest: GeneratedGuest = create_generated_guest()
        reservation_date: str = "2026-11-05"
        async with create_domain_facade(restaurant_database_path) as first_domain_facade:
            created_reservation: Reservation = await first_domain_facade.create_reservation(
                ReservationRequest(
                    guest_name=generated_guest.guest_name,
                    phone_number=generated_guest.phone_digits,
                    party_size=2,
                    reservation_date=reservation_date,
                    reservation_time="18:00",
                    notes=None,
                )
            )
        expected_reservations: list[Reservation] = [created_reservation]

        async with create_domain_facade(restaurant_database_path) as second_domain_facade:
            actual_found_reservations: list[Reservation] = await second_domain_facade.find_reservations(
                ReservationSearchRequest(
                    phone_number=generated_guest.phone_digits, guest_name=generated_guest.guest_name, reservation_date=reservation_date
                )
            )

        assert actual_found_reservations == expected_reservations

    async def test_GetRestaurantProfile_WhenTheStoreWasCreatedByAnOlderVersion_ThenTheFailureSaysToDeleteTheStore(
        self, older_store_database_path: Path
    ) -> None:
        expected_message_phrases: list[str] = [f"store version {OLDER_STORE_VERSION}", "Delete the store file"]
        expected_exception_metadata: ExpectedExceptionMetadata = ExpectedExceptionMetadata(
            http_status_code=500,
            exception_action=ExceptionAction.DEVELOPER_ACTION_REQUIRED,
            reason="The restaurant store breaks a contract the domain relies on",
            severity=Severity.ERROR,
            log_event=LogEventRestaurantStore.RESTAURANT_STORE_OPERATION,
        )
        expected_contextual_data_by_name: dict[str, int] = {"RestaurantStore.Version": OLDER_STORE_VERSION}
        expected_present_contextual_data_names: list[str] = ["RestaurantStore.RequiredVersion"]

        async with create_domain_facade(older_store_database_path) as domain_facade:
            with pytest.raises(RestaurantStoreContractViolationException) as raised:
                await domain_facade.get_restaurant_profile()

        AsserterException.assert_message_and_metadata_are_as_expected(
            expected_exception_content=ExpectedExceptionContent(
                message_phrases=expected_message_phrases,
                exception_metadata=expected_exception_metadata,
                contextual_data_by_name=expected_contextual_data_by_name,
                present_contextual_data_names=expected_present_contextual_data_names,
            ),
            actual_voice_agent_restaurant_exception=raised.value,
        )

    async def test_GetRestaurantProfile_WhenTheStoreFileIsNotASqliteDatabase_ThenTheFailureIsReportedAsPermanent(
        self, foreign_file_database_path: Path
    ) -> None:
        store_operation: str = "read the restaurant profile"
        expected_message_phrases: list[str] = [store_operation, "retrying will not help"]
        expected_exception_metadata: ExpectedExceptionMetadata = ExpectedExceptionMetadata(
            http_status_code=500,
            exception_action=ExceptionAction.DEVELOPER_ACTION_REQUIRED,
            reason="The restaurant store breaks a contract the domain relies on",
            severity=Severity.ERROR,
            log_event=LogEventRestaurantStore.RESTAURANT_STORE_OPERATION,
        )
        expected_contextual_data_by_name: dict[str, str] = {"RestaurantStore.Operation": store_operation}
        # The driver's error type and text are its own; that they are recorded is what the diagnosis needs.
        expected_present_contextual_data_names: list[str] = ["RestaurantStore.ErrorType", "RestaurantStore.Error"]

        async with create_domain_facade(foreign_file_database_path) as domain_facade:
            with pytest.raises(RestaurantStoreContractViolationException) as raised:
                await domain_facade.get_restaurant_profile()

        AsserterException.assert_message_and_metadata_are_as_expected(
            expected_exception_content=ExpectedExceptionContent(
                message_phrases=expected_message_phrases,
                exception_metadata=expected_exception_metadata,
                contextual_data_by_name=expected_contextual_data_by_name,
                present_contextual_data_names=expected_present_contextual_data_names,
            ),
            actual_voice_agent_restaurant_exception=raised.value,
        )

    @pytest.mark.parametrize(
        ("environment_variables", "expected_absence_phrase", "expected_setting_was_missing"),
        [
            ({}, "was missing", True),
            ({DATABASE_PATH_VARIABLE_NAME: "   "}, "was empty or whitespace", False),
        ],
    )
    def test_DomainFacade_WhenTheDatabasePathSettingIsMissingOrBlank_ThenConstructionFailsNamingTheSetting(
        self, environment_variables: dict[str, str], expected_absence_phrase: str, expected_setting_was_missing: bool
    ) -> None:
        expected_message_phrases: list[str] = [DATABASE_PATH_VARIABLE_NAME, expected_absence_phrase]
        expected_exception_metadata: ExpectedExceptionMetadata = create_configuration_refusal_metadata()
        expected_contextual_data_by_name: dict[str, str | bool] = {
            ENVIRONMENT_VARIABLE_NAME_CONTEXT_NAME: DATABASE_PATH_VARIABLE_NAME,
            "Configuration.SettingWasMissing": expected_setting_was_missing,
        }

        with pytest.raises(ConfigurationSettingException) as raised:
            DomainFacade(ServiceLocatorTesting(environment_variables, WEDNESDAY_AFTERNOON_UTC))

        AsserterException.assert_message_and_metadata_are_as_expected(
            expected_exception_content=ExpectedExceptionContent(
                message_phrases=expected_message_phrases,
                exception_metadata=expected_exception_metadata,
                contextual_data_by_name=expected_contextual_data_by_name,
            ),
            actual_voice_agent_restaurant_exception=raised.value,
        )

    def test_DomainFacade_WhenTheDatabasePathContainsANulCharacter_ThenConstructionFailsNamingTheSetting(self) -> None:
        unusable_database_path: str = "data/restaurant" + chr(0) + ".sqlite3"
        expected_message_phrases: list[str] = [DATABASE_PATH_VARIABLE_NAME, "NUL character"]
        expected_exception_metadata: ExpectedExceptionMetadata = create_configuration_refusal_metadata()
        expected_contextual_data_by_name: dict[str, str] = {ENVIRONMENT_VARIABLE_NAME_CONTEXT_NAME: DATABASE_PATH_VARIABLE_NAME}

        with pytest.raises(ConfigurationSettingException) as raised:
            DomainFacade(ServiceLocatorTesting({DATABASE_PATH_VARIABLE_NAME: unusable_database_path}, WEDNESDAY_AFTERNOON_UTC))

        AsserterException.assert_message_and_metadata_are_as_expected(
            expected_exception_content=ExpectedExceptionContent(
                message_phrases=expected_message_phrases,
                exception_metadata=expected_exception_metadata,
                contextual_data_by_name=expected_contextual_data_by_name,
            ),
            actual_voice_agent_restaurant_exception=raised.value,
        )
