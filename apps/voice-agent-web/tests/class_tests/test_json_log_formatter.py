# Class tests for JsonLogFormatter. They prove each log line is one JSON object carrying the level, logger and message,
# that fields passed as event_fields appear at the top level, and that an exception travels in its own field.

import json
import logging
import secrets
from datetime import UTC, datetime
from typing import Final

from web_test_support.generated_words import create_generated_word

from voice_agent_web.json_log_formatter import JsonLogFormatter

LOGGER_NAME: Final[str] = "voice_agent_web.handlers.conversation_handler"


def create_log_record(message: str, exc_info: logging._SysExcInfoType | None = None) -> logging.LogRecord:
    return logging.LogRecord(LOGGER_NAME, logging.INFO, __file__, 1, message, None, exc_info)


class TestJsonLogFormatter:
    def test_Format_WhenARecordCarriesEventFields_ThenTheLineIsOneJsonObjectWithThoseFieldsAtTheTopLevel(self) -> None:
        json_log_formatter: JsonLogFormatter = JsonLogFormatter()
        logged_message: str = create_generated_word()
        event_name: str = create_generated_word()
        conversation_id: str = secrets.token_hex(16)
        # A quarter second is exact in binary, so the recorded stamp survives the float round trip to the millisecond.
        recorded_at: datetime = datetime(2026, 11, 12, 9, 30, 15, 250000, tzinfo=UTC)
        log_record: logging.LogRecord = create_log_record(logged_message)
        log_record.created = recorded_at.timestamp()
        log_record.event_fields = {"event": event_name, "conversation_id": conversation_id}
        expected_fields: dict[str, object] = {
            "time": "2026-11-12T09:30:15.250+00:00",
            "level": "INFO",
            "logger": LOGGER_NAME,
            "message": logged_message,
            "event": event_name,
            "conversation_id": conversation_id,
        }

        actual_line: str = json_log_formatter.format(log_record)

        actual_fields: dict[str, object] = json.loads(actual_line)
        assert actual_fields == expected_fields

    def test_Format_WhenARecordCarriesAnException_ThenItIsInTheExceptionField(self) -> None:
        json_log_formatter: JsonLogFormatter = JsonLogFormatter()
        failure_detail: str = create_generated_word()
        os_error: OSError = OSError(failure_detail)
        log_record: logging.LogRecord = create_log_record("Request failed unexpectedly", (OSError, os_error, None))
        expected_exception_text: str = f"OSError: {failure_detail}"

        actual_line: str = json_log_formatter.format(log_record)

        actual_exception_text: str = str(json.loads(actual_line)["exception"])
        assert actual_exception_text == expected_exception_text
