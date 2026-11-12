# Class tests for HostSettingsProvider and the entry point that starts the host from it. They prove unset settings fall
# back to the defaults, set ones are read and checked, a setting that cannot be used is refused with a HostSettingException
# naming it, and that main() stops with the setting's message in the log, not a traceback, when a setting cannot be used.

import logging
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pytest
from web_test_support.asserter_host_setting_exception import AsserterHostSettingException, ExpectedHostSettingRefusal
from web_test_support.generated_words import create_generated_word

from voice_agent_web import entry_point
from voice_agent_web.configuration_providers.host_settings import HostSettings
from voice_agent_web.configuration_providers.host_settings_provider import HostSettingsProvider
from voice_agent_web.configuration_providers.host_settings_source import HostSettingsSource
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


@dataclass(frozen=True)
class StartupRefusal:
    """How main() stopped: its exit code, and for each error it logged whether it named the problem and had a traceback."""

    exit_code: str | int | None
    logged_errors_naming_the_problem: list[bool]
    logged_errors_with_a_traceback: list[bool]


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

        actual_host_settings: HostSettings = HostSettingsProvider(HostSettingsSource({})).get_host_settings()

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
            HostSettingsSource(
                {
                    HOST_VARIABLE_NAME: f" {listening_host} ",
                    PORT_VARIABLE_NAME: f" {port} ",
                    ALLOWED_ORIGINS_VARIABLE_NAME: f" {booking_site_origin.upper()}/ , ,{local_site_origin}",
                    MAXIMUM_CONCURRENT_CALLS_VARIABLE_NAME: str(maximum_concurrent_calls),
                }
            )
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
            HostSettingsProvider(HostSettingsSource({variable_name: setting_text}))

        AsserterHostSettingException.assert_refused_host_setting_is_as_expected(expected_host_setting_refusal, raised.value)

    def test_GetHostSettings_WhenThePortIsOutsideTheRange_ThenTheProviderRefusesItNamingThePort(self) -> None:
        expected_host_setting_refusal: ExpectedHostSettingRefusal = ExpectedHostSettingRefusal(
            setting_name="port", setting_value="0", message_phrases=("must be between 1 and 65535",)
        )

        with pytest.raises(HostSettingException) as raised:
            HostSettingsProvider(HostSettingsSource({PORT_VARIABLE_NAME: "0"}))

        AsserterHostSettingException.assert_refused_host_setting_is_as_expected(expected_host_setting_refusal, raised.value)

    def test_GetHostSettings_WhenNoCallSlotIsAllowed_ThenTheProviderRefusesItNamingTheCallLimit(self) -> None:
        expected_host_setting_refusal: ExpectedHostSettingRefusal = ExpectedHostSettingRefusal(
            setting_name="maximum_concurrent_calls", setting_value="0", message_phrases=("must be at least 1",)
        )

        with pytest.raises(HostSettingException) as raised:
            HostSettingsProvider(HostSettingsSource({MAXIMUM_CONCURRENT_CALLS_VARIABLE_NAME: "0"}))

        AsserterHostSettingException.assert_refused_host_setting_is_as_expected(expected_host_setting_refusal, raised.value)

    def test_GetHostSettings_WhenAnAllowedOriginNamesNoScheme_ThenTheProviderRefusesItNamingTheOrigin(self) -> None:
        bare_host_origin: str = create_generated_host()
        expected_host_setting_refusal: ExpectedHostSettingRefusal = ExpectedHostSettingRefusal(
            setting_name="allowed_origins", setting_value=bare_host_origin, message_phrases=("must name a scheme and a host",)
        )

        with pytest.raises(HostSettingException) as raised:
            HostSettingsProvider(HostSettingsSource({ALLOWED_ORIGINS_VARIABLE_NAME: bare_host_origin}))

        AsserterHostSettingException.assert_refused_host_setting_is_as_expected(expected_host_setting_refusal, raised.value)


class TestEntryPoint:
    @pytest.fixture(autouse=True)
    def keep_main_from_loading_env_or_serving(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def skip_loading_the_env_file() -> bool:
            # main() loads .env into the process environment, where no monkeypatch would undo it for the tests that follow.
            return False

        def refuse_to_serve(*_server_arguments: object, **_server_options: object) -> None:
            # A startup refusal that stopped working would otherwise start a real server and hang the test run.
            raise AssertionError("main() started serving although a setting could not be used.")

        monkeypatch.setattr(entry_point, "load_dotenv", skip_loading_the_env_file)
        monkeypatch.setattr(entry_point.uvicorn, "run", refuse_to_serve)

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
        expected_startup_refusal: StartupRefusal = StartupRefusal(
            exit_code=STARTUP_FAILURE_EXIT_CODE, logged_errors_naming_the_problem=[True], logged_errors_with_a_traceback=[False]
        )

        with caplog.at_level(logging.ERROR, logger=ENTRY_POINT_LOGGER_NAME), pytest.raises(SystemExit) as raised:
            entry_point.main()

        actual_startup_refusal: StartupRefusal = StartupRefusal(
            exit_code=raised.value.code,
            logged_errors_naming_the_problem=[expected_message_phrase in entry_point_error for entry_point_error in read_entry_point_errors(caplog)],
            logged_errors_with_a_traceback=read_entry_point_tracebacks(caplog),
        )
        assert actual_startup_refusal == expected_startup_refusal

    def test_Main_WhenTheApiKeyIsEmpty_ThenTheProcessStopsAndTheLogNamesTheKeyWithoutATraceback(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, tmp_path: Path
    ) -> None:
        monkeypatch.setenv(API_KEY_VARIABLE_NAME, "")
        monkeypatch.setenv(DATABASE_PATH_VARIABLE_NAME, str(tmp_path / "restaurant.sqlite3"))
        monkeypatch.delenv(PORT_VARIABLE_NAME, raising=False)
        expected_startup_refusal: StartupRefusal = StartupRefusal(
            exit_code=STARTUP_FAILURE_EXIT_CODE, logged_errors_naming_the_problem=[True], logged_errors_with_a_traceback=[False]
        )

        with caplog.at_level(logging.ERROR, logger=ENTRY_POINT_LOGGER_NAME), pytest.raises(SystemExit) as raised:
            entry_point.main()

        actual_startup_refusal: StartupRefusal = StartupRefusal(
            exit_code=raised.value.code,
            logged_errors_naming_the_problem=[API_KEY_VARIABLE_NAME in entry_point_error for entry_point_error in read_entry_point_errors(caplog)],
            logged_errors_with_a_traceback=read_entry_point_tracebacks(caplog),
        )
        assert actual_startup_refusal == expected_startup_refusal
