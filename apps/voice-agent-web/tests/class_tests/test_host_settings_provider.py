# Class tests for HostSettingsProvider and the entry point that starts the host from it. They prove unset settings fall
# back to the defaults, set ones are read and checked, a setting that cannot be used is refused with a HostSettingException
# naming it, and that main() stops with the setting's message in the log, not a traceback, when a setting cannot be used.

import logging
import secrets
from pathlib import Path
from typing import Final

import pytest
from web_test_support.asserter_host_setting_exception import AsserterHostSettingException, ExpectedHostSettingRefusal
from web_test_support.generated_words import create_generated_word

from voice_agent_web import entry_point
from voice_agent_web.configuration_providers.host_settings import HostSettings
from voice_agent_web.configuration_providers.host_settings_provider import HostSettingsProvider
from voice_agent_web.exceptions.host_setting_exception import HostSettingException

PORT_VARIABLE_NAME: Final[str] = "VOICE_AGENT_WEB_PORT"
HOST_VARIABLE_NAME: Final[str] = "VOICE_AGENT_WEB_HOST"
ALLOWED_ORIGINS_VARIABLE_NAME: Final[str] = "VOICE_AGENT_WEB_ALLOWED_ORIGINS"
MAXIMUM_CONCURRENT_CALLS_VARIABLE_NAME: Final[str] = "VOICE_AGENT_MAXIMUM_CONCURRENT_CALLS"
API_KEY_VARIABLE_NAME: Final[str] = "OPENAI_API_KEY"
DATABASE_PATH_VARIABLE_NAME: Final[str] = "VOICE_AGENT_RESTAURANT_DATABASE_PATH"
ENTRY_POINT_LOGGER_NAME: Final[str] = "voice_agent_web.entry_point"
STARTUP_FAILURE_EXIT_CODE: Final[int] = 1
WHOLE_NUMBER_PROBLEM_PHRASE: Final[str] = "must be a whole number"
# "10" in fullwidth digits, which int() would accept.
FULLWIDTH_DIGITS_TEN: Final[str] = chr(0xFF11) + chr(0xFF10)


def create_generated_port() -> int:
    return 1_024 + secrets.randbelow(60_000)


def create_generated_host() -> str:
    return f"{create_generated_word().lower()}.example.com"


def read_entry_point_errors(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        log_record.getMessage() for log_record in caplog.records if log_record.name == ENTRY_POINT_LOGGER_NAME and log_record.levelno == logging.ERROR
    ]


def read_entry_point_tracebacks(caplog: pytest.LogCaptureFixture) -> list[bool]:
    return [log_record.exc_info is not None for log_record in caplog.records if log_record.name == ENTRY_POINT_LOGGER_NAME]


class TestHostSettingsProvider:
    def test_GetHostSettings_WhenNothingIsSet_ThenTheDefaultsAreUsed(self) -> None:
        expected_host_settings: HostSettings = HostSettings(
            host=HostSettingsProvider.DEFAULT_HOST,
            port=HostSettingsProvider.DEFAULT_PORT,
            allowed_origins=frozenset(),
            maximum_concurrent_calls=HostSettingsProvider.DEFAULT_MAXIMUM_CONCURRENT_CALLS,
        )

        actual_host_settings: HostSettings = HostSettingsProvider({}).get_host_settings()

        assert actual_host_settings == expected_host_settings

    def test_GetHostSettings_WhenEverySettingIsSet_ThenEachIsReadAndTheOriginsAreSplitTrimmedAndNormalized(self) -> None:
        listening_host: str = create_generated_host()
        port: int = create_generated_port()
        maximum_concurrent_calls: int = 1 + secrets.randbelow(50)
        booking_site_origin: str = f"https://{create_generated_host()}"
        local_site_origin: str = f"http://{create_generated_host()}:{create_generated_port()}"
        expected_host_settings: HostSettings = HostSettings(
            host=listening_host,
            port=port,
            allowed_origins=frozenset({booking_site_origin, local_site_origin}),
            maximum_concurrent_calls=maximum_concurrent_calls,
        )

        actual_host_settings: HostSettings = HostSettingsProvider(
            {
                HOST_VARIABLE_NAME: f" {listening_host} ",
                PORT_VARIABLE_NAME: f" {port} ",
                ALLOWED_ORIGINS_VARIABLE_NAME: f" {booking_site_origin.upper()}/ , ,{local_site_origin}",
                MAXIMUM_CONCURRENT_CALLS_VARIABLE_NAME: str(maximum_concurrent_calls),
            }
        ).get_host_settings()

        assert actual_host_settings == expected_host_settings

    @pytest.mark.parametrize(
        ("variable_name", "setting_text"),
        [
            pytest.param(PORT_VARIABLE_NAME, "eighty", id="port in words"),
            pytest.param(PORT_VARIABLE_NAME, "-8000", id="negative port"),
            pytest.param(MAXIMUM_CONCURRENT_CALLS_VARIABLE_NAME, "2.5", id="fractional call limit"),
            pytest.param(MAXIMUM_CONCURRENT_CALLS_VARIABLE_NAME, FULLWIDTH_DIGITS_TEN, id="fullwidth digits"),
        ],
    )
    def test_GetHostSettings_WhenAWholeNumberSettingIsNotOne_ThenAHostSettingExceptionNamesTheSettingAndTheValue(
        self, variable_name: str, setting_text: str
    ) -> None:
        expected_host_setting_refusal: ExpectedHostSettingRefusal = ExpectedHostSettingRefusal(
            setting_name=variable_name, setting_value=setting_text, message_phrases=(WHOLE_NUMBER_PROBLEM_PHRASE,)
        )

        with pytest.raises(HostSettingException) as raised:
            HostSettingsProvider({variable_name: setting_text})

        AsserterHostSettingException.assert_refused_host_setting_is_as_expected(expected_host_setting_refusal, raised.value)

    @pytest.mark.parametrize(
        ("variable_name", "setting_text", "expected_host_setting_refusal"),
        [
            pytest.param(
                PORT_VARIABLE_NAME, "0", ExpectedHostSettingRefusal("port", "0", ("must be between 1 and 65535",)), id="port outside the range"
            ),
            pytest.param(
                MAXIMUM_CONCURRENT_CALLS_VARIABLE_NAME,
                "0",
                ExpectedHostSettingRefusal("maximum_concurrent_calls", "0", ("must be at least 1",)),
                id="no call slot",
            ),
            pytest.param(
                ALLOWED_ORIGINS_VARIABLE_NAME,
                "booking.example.com",
                ExpectedHostSettingRefusal("allowed_origins", "booking.example.com", ("must name a scheme and a host",)),
                id="origin with no scheme",
            ),
        ],
    )
    def test_GetHostSettings_WhenAReadSettingCannotBeUsed_ThenTheProviderRefusesItBeforeAnyoneReadsTheSettings(
        self, variable_name: str, setting_text: str, expected_host_setting_refusal: ExpectedHostSettingRefusal
    ) -> None:
        with pytest.raises(HostSettingException) as raised:
            HostSettingsProvider({variable_name: setting_text})

        AsserterHostSettingException.assert_refused_host_setting_is_as_expected(expected_host_setting_refusal, raised.value)


class TestEntryPoint:
    @pytest.fixture(autouse=True)
    def ignore_the_developers_env_file(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # main() loads .env into the process environment, where no monkeypatch would undo it for the tests that follow.
        monkeypatch.setattr(entry_point, "load_dotenv", lambda: False)

    @pytest.mark.parametrize(
        ("port_text", "expected_message_phrase"),
        [
            pytest.param("eighty", f"{PORT_VARIABLE_NAME}' {WHOLE_NUMBER_PROBLEM_PHRASE}", id="not a number"),
            pytest.param("0", "must be between 1 and 65535", id="outside the range"),
        ],
    )
    def test_Main_WhenThePortCannotBeUsed_ThenTheProcessStopsAndTheLogNamesTheProblemWithoutATraceback(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, port_text: str, expected_message_phrase: str
    ) -> None:
        monkeypatch.setenv(PORT_VARIABLE_NAME, port_text)
        # One error entry, naming the problem, and no traceback.
        expected_outcome: tuple[int, list[bool], list[bool]] = (STARTUP_FAILURE_EXIT_CODE, [True], [False])

        with caplog.at_level(logging.ERROR, logger=ENTRY_POINT_LOGGER_NAME), pytest.raises(SystemExit) as raised:
            entry_point.main()

        actual_outcome: tuple[int, list[bool], list[bool]] = (
            raised.value.code,
            [expected_message_phrase in entry_point_error for entry_point_error in read_entry_point_errors(caplog)],
            read_entry_point_tracebacks(caplog),
        )
        assert actual_outcome == expected_outcome

    def test_Main_WhenTheApiKeyIsEmpty_ThenTheProcessStopsAndTheLogNamesTheKeyWithoutATraceback(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, tmp_path: Path
    ) -> None:
        monkeypatch.setenv(API_KEY_VARIABLE_NAME, "")
        monkeypatch.setenv(DATABASE_PATH_VARIABLE_NAME, str(tmp_path / "restaurant.sqlite3"))
        monkeypatch.delenv(PORT_VARIABLE_NAME, raising=False)
        # One error entry, naming the key, and no traceback.
        expected_outcome: tuple[int, list[bool], list[bool]] = (STARTUP_FAILURE_EXIT_CODE, [True], [False])

        with caplog.at_level(logging.ERROR, logger=ENTRY_POINT_LOGGER_NAME), pytest.raises(SystemExit) as raised:
            entry_point.main()

        actual_outcome: tuple[int, list[bool], list[bool]] = (
            raised.value.code,
            [API_KEY_VARIABLE_NAME in entry_point_error for entry_point_error in read_entry_point_errors(caplog)],
            read_entry_point_tracebacks(caplog),
        )
        assert actual_outcome == expected_outcome
