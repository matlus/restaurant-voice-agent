# Class tests for the seed reader's checks. The bundled seed always passes them, so no DomainFacade scenario can reach a
# broken seed; each test copies the bundled seed into a temporary directory, breaks one value and reads that copy.

import json
from collections.abc import Callable
from importlib import resources
from pathlib import Path
from typing import Any, Final

import pytest

from voice_agent_restaurant import ExceptionAction, RestaurantSeedDataInvalidException, Severity
from voice_agent_restaurant.managers.data_managers.store.initialization.seed_data.seed_data_reader import RestaurantSeed, SeedDataReader
from voice_agent_restaurant.managers.data_managers.store.initialization.seed_data.seed_values.seed_file import SeedFile

type SeedChange = Callable[[dict[str, Any]], None]
type ContextualDataValue = str | int | float | bool

SEED_DATA_INVALID_REASON: Final[str] = "The restaurant seed data is invalid"
SEED_DATA_INVALID_HTTP_STATUS_CODE: Final[int] = 500


def copy_bundled_seed(seed_directory: Path) -> Path:
    seed_directory.mkdir()
    for file_name in (
        SeedDataReader.RESTAURANT_FILE_NAME,
        SeedDataReader.TABLES_FILE_NAME,
        SeedDataReader.MENU_FILE_NAME,
        SeedDataReader.RESERVATIONS_FILE_NAME,
    ):
        bundled_text: str = resources.files("voice_agent_restaurant").joinpath("seed_data", file_name).read_text(encoding="utf-8")
        (seed_directory / file_name).write_text(bundled_text, encoding="utf-8")
    return seed_directory


def change_seed_file(seed_directory: Path, file_name: str, seed_change: SeedChange) -> None:
    seed_file_path: Path = seed_directory / file_name
    root_object: dict[str, Any] = json.loads(seed_file_path.read_text(encoding="utf-8"))
    seed_change(root_object)
    seed_file_path.write_text(json.dumps(root_object), encoding="utf-8")


def create_broken_seed(tmp_path: Path, file_name: str, seed_change: SeedChange) -> Path:
    seed_directory: Path = copy_bundled_seed(tmp_path / "seed_data")
    change_seed_file(seed_directory, file_name, seed_change)
    return seed_directory


def assert_seed_refusal_is_as_expected(
    *,
    expected_file_name: str,
    expected_value_path: str | None,
    expected_message_phrase: str,
    actual_restaurant_seed_data_invalid_exception: RestaurantSeedDataInvalidException,
) -> None:
    actual_contextual_data_by_name: dict[str, ContextualDataValue] = actual_restaurant_seed_data_invalid_exception.contextual_data_by_name
    expected_obligations: list[tuple[str, object, object]] = [
        ("File name context", expected_file_name, actual_contextual_data_by_name.get(SeedFile.FILE_NAME_CONTEXT_KEY)),
        ("Value path context", expected_value_path, actual_contextual_data_by_name.get(SeedFile.VALUE_PATH_CONTEXT_KEY)),
        ("Action", ExceptionAction.DEVELOPER_ACTION_REQUIRED, actual_restaurant_seed_data_invalid_exception.action),
        ("HTTP status", SEED_DATA_INVALID_HTTP_STATUS_CODE, actual_restaurant_seed_data_invalid_exception.http_status_code),
        ("Reason", SEED_DATA_INVALID_REASON, actual_restaurant_seed_data_invalid_exception.reason),
        ("Severity", Severity.ERROR, actual_restaurant_seed_data_invalid_exception.severity),
    ]
    mismatch_messages: list[str] = [
        f"{obligation_name}: expected {expected_value!r}; actual {actual_value!r}."
        for obligation_name, expected_value, actual_value in expected_obligations
        if expected_value != actual_value
    ]
    if expected_message_phrase not in actual_restaurant_seed_data_invalid_exception.message:
        mismatch_messages.append(f"Message is missing {expected_message_phrase!r}.")
    failure_report: str = "\n".join(mismatch_messages)
    assert not failure_report, (
        f"A broken seed must be refused naming '{expected_file_name}' and value path {expected_value_path!r}, saying "
        f"{expected_message_phrase!r}, and asking a developer to fix it (actual message: "
        f"{actual_restaurant_seed_data_invalid_exception.message!r}); {len(mismatch_messages)} mismatches:\n{failure_report}"
    )


def close_friday_at_midnight(restaurant_object: dict[str, Any]) -> None:
    restaurant_object["weekly_hours"][4]["closes_at"] = "00:00"


def remove_the_slot_interval(restaurant_object: dict[str, Any]) -> None:
    restaurant_object["reservation_policy"]["slot_interval_minutes"] = 0


def set_a_slot_interval_that_does_not_divide_an_hour(restaurant_object: dict[str, Any]) -> None:
    restaurant_object["reservation_policy"]["slot_interval_minutes"] = 25


def open_friday_off_the_slot_grid(restaurant_object: dict[str, Any]) -> None:
    restaurant_object["weekly_hours"][4]["opens_at"] = "17:10"


def cap_parties_below_the_minimum(restaurant_object: dict[str, Any]) -> None:
    restaurant_object["reservation_policy"]["minimum_party_size"] = 4
    restaurant_object["reservation_policy"]["maximum_party_size"] = 2


def give_a_table_no_seats(tables_object: dict[str, Any]) -> None:
    tables_object["tables"][0]["seats"] = 0


def seat_a_booking_too_late_to_finish(reservations_object: dict[str, Any]) -> None:
    reservations_object["reservations"][0]["starts_at"] = "22:00"


def seat_two_bookings_at_one_table(reservations_object: dict[str, Any]) -> None:
    reservations_object["reservations"][1]["table_id"] = reservations_object["reservations"][0]["table_id"]


def create_confirmation_code_change(seeded_confirmation_code: str) -> SeedChange:
    def give_the_first_booking_the_code(reservations_object: dict[str, Any]) -> None:
        reservations_object["reservations"][0]["confirmation_code"] = seeded_confirmation_code

    return give_the_first_booking_the_code


def create_phone_number_change(seeded_phone_number: str) -> SeedChange:
    def give_the_first_booking_the_phone_number(reservations_object: dict[str, Any]) -> None:
        reservations_object["reservations"][0]["phone_number"] = seeded_phone_number

    return give_the_first_booking_the_phone_number


class TestSeedDataReaderBundledSeed:
    def test_ReadRestaurantSeed_WhenTheBundledSeedIsCopied_ThenEveryBookingIsRead(self, tmp_path: Path) -> None:
        seed_directory: Path = copy_bundled_seed(tmp_path / "seed_data")
        expected_seed_reservation_count: int = len(
            json.loads((seed_directory / SeedDataReader.RESERVATIONS_FILE_NAME).read_text(encoding="utf-8"))["reservations"]
        )

        actual_restaurant_seed: RestaurantSeed = SeedDataReader.read_restaurant_seed(seed_directory)

        assert len(actual_restaurant_seed.seed_reservations) == expected_seed_reservation_count

    def test_ReadRestaurantSeed_WhenASeedFileIsMissing_ThenTheRefusalNamesTheFile(self, tmp_path: Path) -> None:
        seed_directory: Path = copy_bundled_seed(tmp_path / "seed_data")
        (seed_directory / SeedDataReader.MENU_FILE_NAME).unlink()
        expected_file_name: str = SeedDataReader.MENU_FILE_NAME
        expected_value_path: str | None = None
        expected_message_phrase: str = "cannot be read"

        with pytest.raises(RestaurantSeedDataInvalidException) as raised:
            SeedDataReader.read_restaurant_seed(seed_directory)

        assert_seed_refusal_is_as_expected(
            expected_file_name=expected_file_name,
            expected_value_path=expected_value_path,
            expected_message_phrase=expected_message_phrase,
            actual_restaurant_seed_data_invalid_exception=raised.value,
        )

    def test_ReadRestaurantSeed_WhenASeedFileIsNotInUtf8_ThenTheRefusalNamesTheFile(self, tmp_path: Path) -> None:
        seed_directory: Path = copy_bundled_seed(tmp_path / "seed_data")
        menu_seed_path: Path = seed_directory / SeedDataReader.MENU_FILE_NAME
        # An accented dish name saved by an editor in a Windows code page is not valid UTF-8.
        menu_seed_path.write_bytes(menu_seed_path.read_text(encoding="utf-8").replace("Ember Caesar", "Ember Caf\u00e9 Caesar").encode("cp1252"))
        expected_file_name: str = SeedDataReader.MENU_FILE_NAME
        expected_value_path: str | None = None
        expected_message_phrase: str = "cannot be read"

        with pytest.raises(RestaurantSeedDataInvalidException) as raised:
            SeedDataReader.read_restaurant_seed(seed_directory)

        assert_seed_refusal_is_as_expected(
            expected_file_name=expected_file_name,
            expected_value_path=expected_value_path,
            expected_message_phrase=expected_message_phrase,
            actual_restaurant_seed_data_invalid_exception=raised.value,
        )


class TestSeedDataReaderOpeningHours:
    def test_ReadRestaurantSeed_WhenADayClosesAtMidnight_ThenTheRefusalSaysServiceCannotRunPastMidnight(self, tmp_path: Path) -> None:
        seed_directory: Path = create_broken_seed(tmp_path, SeedDataReader.RESTAURANT_FILE_NAME, close_friday_at_midnight)
        expected_file_name: str = SeedDataReader.RESTAURANT_FILE_NAME
        expected_value_path: str = "$.weekly_hours[4]"
        expected_message_phrase: str = "cannot run past midnight"

        with pytest.raises(RestaurantSeedDataInvalidException) as raised:
            SeedDataReader.read_restaurant_seed(seed_directory)

        assert_seed_refusal_is_as_expected(
            expected_file_name=expected_file_name,
            expected_value_path=expected_value_path,
            expected_message_phrase=expected_message_phrase,
            actual_restaurant_seed_data_invalid_exception=raised.value,
        )

    def test_ReadRestaurantSeed_WhenADayOpensOffTheSlotGrid_ThenTheRefusalNamesTheOpeningTime(self, tmp_path: Path) -> None:
        seed_directory: Path = create_broken_seed(tmp_path, SeedDataReader.RESTAURANT_FILE_NAME, open_friday_off_the_slot_grid)
        expected_file_name: str = SeedDataReader.RESTAURANT_FILE_NAME
        expected_value_path: str = "$.weekly_hours[4].opens_at"
        expected_message_phrase: str = "must fall on the 15-minute slot grid"

        with pytest.raises(RestaurantSeedDataInvalidException) as raised:
            SeedDataReader.read_restaurant_seed(seed_directory)

        assert_seed_refusal_is_as_expected(
            expected_file_name=expected_file_name,
            expected_value_path=expected_value_path,
            expected_message_phrase=expected_message_phrase,
            actual_restaurant_seed_data_invalid_exception=raised.value,
        )


class TestSeedDataReaderReservationPolicy:
    def test_ReadRestaurantSeed_WhenTheSlotIntervalIsZero_ThenTheRefusalSaysItMustBePositive(self, tmp_path: Path) -> None:
        seed_directory: Path = create_broken_seed(tmp_path, SeedDataReader.RESTAURANT_FILE_NAME, remove_the_slot_interval)
        expected_file_name: str = SeedDataReader.RESTAURANT_FILE_NAME
        expected_value_path: str = "$.reservation_policy.slot_interval_minutes"
        expected_message_phrase: str = "must be at least 1"

        with pytest.raises(RestaurantSeedDataInvalidException) as raised:
            SeedDataReader.read_restaurant_seed(seed_directory)

        assert_seed_refusal_is_as_expected(
            expected_file_name=expected_file_name,
            expected_value_path=expected_value_path,
            expected_message_phrase=expected_message_phrase,
            actual_restaurant_seed_data_invalid_exception=raised.value,
        )

    def test_ReadRestaurantSeed_WhenTheSlotIntervalDoesNotDivideAnHour_ThenTheRefusalSaysItMust(self, tmp_path: Path) -> None:
        seed_directory: Path = create_broken_seed(tmp_path, SeedDataReader.RESTAURANT_FILE_NAME, set_a_slot_interval_that_does_not_divide_an_hour)
        expected_file_name: str = SeedDataReader.RESTAURANT_FILE_NAME
        expected_value_path: str = "$.reservation_policy.slot_interval_minutes"
        expected_message_phrase: str = "must divide an hour evenly"

        with pytest.raises(RestaurantSeedDataInvalidException) as raised:
            SeedDataReader.read_restaurant_seed(seed_directory)

        assert_seed_refusal_is_as_expected(
            expected_file_name=expected_file_name,
            expected_value_path=expected_value_path,
            expected_message_phrase=expected_message_phrase,
            actual_restaurant_seed_data_invalid_exception=raised.value,
        )

    def test_ReadRestaurantSeed_WhenTheLargestPartyIsBelowTheSmallest_ThenTheRefusalNamesTheMaximum(self, tmp_path: Path) -> None:
        seed_directory: Path = create_broken_seed(tmp_path, SeedDataReader.RESTAURANT_FILE_NAME, cap_parties_below_the_minimum)
        expected_file_name: str = SeedDataReader.RESTAURANT_FILE_NAME
        expected_value_path: str = "$.reservation_policy.maximum_party_size"
        expected_message_phrase: str = "must be at least the minimum_party_size"

        with pytest.raises(RestaurantSeedDataInvalidException) as raised:
            SeedDataReader.read_restaurant_seed(seed_directory)

        assert_seed_refusal_is_as_expected(
            expected_file_name=expected_file_name,
            expected_value_path=expected_value_path,
            expected_message_phrase=expected_message_phrase,
            actual_restaurant_seed_data_invalid_exception=raised.value,
        )


class TestSeedDataReaderTables:
    def test_ReadRestaurantSeed_WhenATableHasNoSeats_ThenTheRefusalNamesTheTable(self, tmp_path: Path) -> None:
        seed_directory: Path = create_broken_seed(tmp_path, SeedDataReader.TABLES_FILE_NAME, give_a_table_no_seats)
        expected_file_name: str = SeedDataReader.TABLES_FILE_NAME
        expected_value_path: str = "$.tables[0].seats"
        expected_message_phrase: str = "must be at least 1"

        with pytest.raises(RestaurantSeedDataInvalidException) as raised:
            SeedDataReader.read_restaurant_seed(seed_directory)

        assert_seed_refusal_is_as_expected(
            expected_file_name=expected_file_name,
            expected_value_path=expected_value_path,
            expected_message_phrase=expected_message_phrase,
            actual_restaurant_seed_data_invalid_exception=raised.value,
        )


class TestSeedDataReaderReservations:
    def test_ReadRestaurantSeed_WhenABookingCannotFinishBeforeClosing_ThenTheRefusalNamesItsStart(self, tmp_path: Path) -> None:
        seed_directory: Path = create_broken_seed(tmp_path, SeedDataReader.RESERVATIONS_FILE_NAME, seat_a_booking_too_late_to_finish)
        expected_file_name: str = SeedDataReader.RESERVATIONS_FILE_NAME
        expected_value_path: str = "$.reservations[0].starts_at"
        expected_message_phrase: str = "leaves no full 90-minute"

        with pytest.raises(RestaurantSeedDataInvalidException) as raised:
            SeedDataReader.read_restaurant_seed(seed_directory)

        assert_seed_refusal_is_as_expected(
            expected_file_name=expected_file_name,
            expected_value_path=expected_value_path,
            expected_message_phrase=expected_message_phrase,
            actual_restaurant_seed_data_invalid_exception=raised.value,
        )

    def test_ReadRestaurantSeed_WhenTwoBookingsHoldOneTableAtOnce_ThenTheRefusalNamesTheLaterBooking(self, tmp_path: Path) -> None:
        seed_directory: Path = create_broken_seed(tmp_path, SeedDataReader.RESERVATIONS_FILE_NAME, seat_two_bookings_at_one_table)
        expected_file_name: str = SeedDataReader.RESERVATIONS_FILE_NAME
        expected_value_path: str = "$.reservations[1].starts_at"
        expected_message_phrase: str = "still holds it"

        with pytest.raises(RestaurantSeedDataInvalidException) as raised:
            SeedDataReader.read_restaurant_seed(seed_directory)

        assert_seed_refusal_is_as_expected(
            expected_file_name=expected_file_name,
            expected_value_path=expected_value_path,
            expected_message_phrase=expected_message_phrase,
            actual_restaurant_seed_data_invalid_exception=raised.value,
        )

    @pytest.mark.parametrize(
        "seeded_confirmation_code",
        [
            pytest.param("kx4tpa", id="lower-case"),
            # 0 is left out of the alphabet because it is easily heard or read as O.
            pytest.param("KX4TP0", id="character-outside-the-alphabet"),
            pytest.param("KX4-TPA", id="separator"),
        ],
    )
    def test_ReadRestaurantSeed_WhenAConfirmationCodeIsNotInItsStoredForm_ThenTheRefusalNamesTheCode(
        self, tmp_path: Path, seeded_confirmation_code: str
    ) -> None:
        seed_directory: Path = create_broken_seed(
            tmp_path, SeedDataReader.RESERVATIONS_FILE_NAME, create_confirmation_code_change(seeded_confirmation_code)
        )
        expected_file_name: str = SeedDataReader.RESERVATIONS_FILE_NAME
        expected_value_path: str = "$.reservations[0].confirmation_code"
        expected_message_phrase: str = f"the form guests' codes are matched in, but was '{seeded_confirmation_code}'"

        with pytest.raises(RestaurantSeedDataInvalidException) as raised:
            SeedDataReader.read_restaurant_seed(seed_directory)

        assert_seed_refusal_is_as_expected(
            expected_file_name=expected_file_name,
            expected_value_path=expected_value_path,
            expected_message_phrase=expected_message_phrase,
            actual_restaurant_seed_data_invalid_exception=raised.value,
        )

    @pytest.mark.parametrize(
        "seeded_phone_number",
        [
            pytest.param("(555) 010-1001", id="separators"),
            pytest.param("+15550101001", id="country-code"),
        ],
    )
    def test_ReadRestaurantSeed_WhenAPhoneNumberIsNotInItsStoredForm_ThenTheRefusalNamesTheNumber(
        self, tmp_path: Path, seeded_phone_number: str
    ) -> None:
        seed_directory: Path = create_broken_seed(tmp_path, SeedDataReader.RESERVATIONS_FILE_NAME, create_phone_number_change(seeded_phone_number))
        expected_file_name: str = SeedDataReader.RESERVATIONS_FILE_NAME
        expected_value_path: str = "$.reservations[0].phone_number"
        expected_message_phrase: str = f"the form guests' numbers are matched in, but was '{seeded_phone_number}'"

        with pytest.raises(RestaurantSeedDataInvalidException) as raised:
            SeedDataReader.read_restaurant_seed(seed_directory)

        assert_seed_refusal_is_as_expected(
            expected_file_name=expected_file_name,
            expected_value_path=expected_value_path,
            expected_message_phrase=expected_message_phrase,
            actual_restaurant_seed_data_invalid_exception=raised.value,
        )
