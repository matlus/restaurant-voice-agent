# Class tests for HostSettingsProvider and the entry point that starts the host from it. They prove unset settings fall
# back to the defaults, set ones are read, a whole-number setting that is not one is refused with a HostSettingException
# naming it, and that main() stops with the setting's message in the log, not a traceback, when a setting cannot be used.

import logging
import secrets
from pathlib import Path
from typing import Final

import pytest

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
# "10" in fullwidth digits, which int() would accept.
FULLWIDTH_DIGITS_TEN: Final[str] = chr(0xFF11) + chr(0xFF10)


def create_generated_port() -> int:
    return 1_024 + secrets.randbelow(60_000)


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
            allowed_origins=[],
            maximum_concurrent_calls=HostSettingsProvider.DEFAULT_MAXIMUM_CONCURRENT_CALLS,
        )

        actual_host_settings: HostSettings = HostSettingsProvider({}).get_host_settings()

        assert actual_host_settings == expected_host_settings

    def test_GetHostSettings_WhenEverySettingIsSet_ThenEachIsReadAndTheOriginsAreSplitAndTrimmed(self) -> None:
        port: int = create_generated_port()
        maximum_concurrent_calls: int = 1 + secrets.randbelow(50)
        expected_host_settings: HostSettings = HostSettings(
            host="localhost",
            port=port,
            allowed_origins=["https://booking.example.com", "http://localhost:5173"],
            maximum_concurrent_calls=maximum_concurrent_calls,
        )

        actual_host_settings: HostSettings = HostSettingsProvider(
            {
                HOST_VARIABLE_NAME: " localhost ",
                PORT_VARIABLE_NAME: f" {port} ",
                ALLOWED_ORIGINS_VARIABLE_NAME: " https://booking.example.com , ,http://localhost:5173",
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
        expected_setting: tuple[str, str] = (variable_name, setting_text)
        expected_message_phrase: str = "must be a whole number"

        with pytest.raises(HostSettingException) as raised:
            HostSettingsProvider({variable_name: setting_text})

        actual_setting: tuple[str, str] = (raised.value.setting_name, raised.value.setting_value)
        assert (actual_setting, expected_message_phrase in str(raised.value)) == (expected_setting, True)


class TestEntryPoint:
    @pytest.mark.parametrize(
        ("port_text", "expected_message_phrase"),
        [
            pytest.param("eighty", f"{PORT_VARIABLE_NAME}' must be a whole number", id="not a number"),
            pytest.param("0", "must be between 1 and 65535", id="outside the range"),
        ],
    )
    def test_Main_WhenThePortCannotBeUsed_ThenTheProcessStopsAndTheLogNamesTheProblemWithoutATraceback(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, port_text: str, expected_message_phrase: str
    ) -> None:
        monkeypatch.setenv(PORT_VARIABLE_NAME, port_text)
        expected_outcome: tuple[int, bool, list[bool]] = (STARTUP_FAILURE_EXIT_CODE, True, [False])

        with caplog.at_level(logging.ERROR, logger=ENTRY_POINT_LOGGER_NAME), pytest.raises(SystemExit) as raised:
            entry_point.main()

        actual_entry_point_errors: list[str] = read_entry_point_errors(caplog)
        actual_outcome: tuple[int, bool, list[bool]] = (
            raised.value.code,
            len(actual_entry_point_errors) == 1 and expected_message_phrase in actual_entry_point_errors[0],
            read_entry_point_tracebacks(caplog),
        )
        assert actual_outcome == expected_outcome

    def test_Main_WhenTheApiKeyIsEmpty_ThenTheProcessStopsAndTheLogNamesTheKeyWithoutATraceback(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, tmp_path: Path
    ) -> None:
        # Set, though empty, so a developer's own .env cannot fill it in when main() loads that file.
        monkeypatch.setenv(API_KEY_VARIABLE_NAME, "")
        monkeypatch.setenv(DATABASE_PATH_VARIABLE_NAME, str(tmp_path / "restaurant.sqlite3"))
        monkeypatch.delenv(PORT_VARIABLE_NAME, raising=False)
        expected_outcome: tuple[int, bool, list[bool]] = (STARTUP_FAILURE_EXIT_CODE, True, [False])

        with caplog.at_level(logging.ERROR, logger=ENTRY_POINT_LOGGER_NAME), pytest.raises(SystemExit) as raised:
            entry_point.main()

        actual_entry_point_errors: list[str] = read_entry_point_errors(caplog)
        actual_outcome: tuple[int, bool, list[bool]] = (
            raised.value.code,
            len(actual_entry_point_errors) == 1 and API_KEY_VARIABLE_NAME in actual_entry_point_errors[0],
            read_entry_point_tracebacks(caplog),
        )
        assert actual_outcome == expected_outcome
