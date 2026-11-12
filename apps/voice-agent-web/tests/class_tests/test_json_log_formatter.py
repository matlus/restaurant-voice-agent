# Class tests for JsonLogFormatter. They prove each log line is one JSON object carrying the level, logger and message,
# that fields passed as event_fields appear at the top level, and that an exception travels in its own field.

import json
import logging
from typing import Final

from voice_agent_web.json_log_formatter import JsonLogFormatter

LOGGER_NAME: Final[str] = "voice_agent_web.handlers.conversation_handler"


def create_log_record(message: str, exc_info: logging._SysExcInfoType | None = None) -> logging.LogRecord:
    return logging.LogRecord(LOGGER_NAME, logging.INFO, __file__, 1, message, None, exc_info)


class TestJsonLogFormatter:
    def test_Format_WhenARecordCarriesEventFields_ThenTheLineIsOneJsonObjectWithThoseFieldsAtTheTopLevel(self) -> None:
        json_log_formatter: JsonLogFormatter = JsonLogFormatter()
        log_record: logging.LogRecord = create_log_record("Call ended")
        log_record.event_fields = {"event": "call_ended", "conversation_id": "0123456789abcdef0123456789abcdef"}
        expected_fields: dict[str, object] = {
            "level": "INFO",
            "logger": LOGGER_NAME,
            "message": "Call ended",
            "event": "call_ended",
            "conversation_id": "0123456789abcdef0123456789abcdef",
        }

        actual_line: str = json_log_formatter.format(log_record)

        actual_fields: dict[str, object] = json.loads(actual_line)
        assert ({name: actual_fields.get(name) for name in expected_fields}, "time" in actual_fields) == (expected_fields, True)

    def test_Format_WhenARecordCarriesAnException_ThenItIsInTheExceptionField(self) -> None:
        json_log_formatter: JsonLogFormatter = JsonLogFormatter()
        failure_detail: str = "the store could not be read"
        os_error: OSError = OSError(failure_detail)
        log_record: logging.LogRecord = create_log_record("Request failed unexpectedly", (OSError, os_error, None))
        expected_exception_text: str = f"OSError: {failure_detail}"

        actual_line: str = json_log_formatter.format(log_record)

        actual_exception_text: str = str(json.loads(actual_line)["exception"])
        assert actual_exception_text == expected_exception_text
