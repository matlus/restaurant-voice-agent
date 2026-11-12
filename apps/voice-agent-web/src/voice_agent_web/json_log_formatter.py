import json
import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Final, cast, final, override


@final
class JsonLogFormatter(logging.Formatter):
    """One JSON object per log line, so the container's log store can query by field. Fields passed with
    extra={"event_fields": {...}} are added at the top level."""

    EVENT_FIELDS_ATTRIBUTE: Final[str] = "event_fields"

    @override
    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, object] = {
            "time": datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        event_fields: object = getattr(record, self.EVENT_FIELDS_ATTRIBUTE, None)
        if isinstance(event_fields, Mapping):
            log_entry.update(cast(Mapping[str, object], event_fields))
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, default=str)
