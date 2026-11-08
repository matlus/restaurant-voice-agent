import json
import traceback
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date, datetime, time
from enum import Enum, IntEnum
from types import TracebackType
from typing import Final, final, override

type ContextualDataDict = dict[str, str | int | float | bool]


class Severity(IntEnum):
    NOT_SET = 0
    DEBUG = 10
    INFORMATION = 20
    WARNING = 30
    ERROR = 40
    CRITICAL = 50


class ExceptionAction(Enum):
    USER_ACTION_REQUIRED = "UserActionRequired"
    RETRY_ACTION_NEEDED = "RetryActionNeeded"
    INFRA_ACTION_REQUIRED = "InfraActionRequired"
    DEVELOPER_ACTION_REQUIRED = "DeveloperActionRequired"
    NO_ACTION_NEEDED = "NoActionNeeded"


class LogEventBase(Enum):
    """Base for structured log event enums. Each domain area defines its own descendant enum."""


@dataclass(frozen=True)
class ExceptionCause:
    exception_type: str
    message: str
    traceback: TracebackType | None = None

    def to_dict(self) -> dict[str, str]:
        cause_data: dict[str, str] = {"exception_type": self.exception_type, "message": self.message}
        if self.traceback:
            cause_data["traceback"] = "".join(traceback.format_tb(self.traceback))
        return cause_data


class VoiceAgentRestaurantBaseException(Exception, ABC):
    """Application base exception for the restaurant domain.

    Abstract, as are its business and technical descendants. Only problem-specific
    leaf exceptions are raised, each from one place in the system.
    """

    APPLICATION_NAME: Final[str] = "VoiceAgentRestaurant"
    TRACEBACK_KEY: Final[str] = "Traceback"

    def __init__(self, message: str, log_event: LogEventBase, contextual_data_by_name: ContextualDataDict | None = None) -> None:
        # CPython does not enforce ABC abstractness for BaseException descendants.
        abstract_method_names: frozenset[str] = type(self).__abstractmethods__
        if abstract_method_names:
            abstract_method_names_display: str = ", ".join(sorted(abstract_method_names))
            raise TypeError(f"Can't instantiate abstract exception class {type(self).__name__} with abstract methods {abstract_method_names_display}")
        super().__init__(message)
        self._message: str = message
        self._log_event: LogEventBase = log_event
        self._additional_contextual_data_by_name: ContextualDataDict = dict(contextual_data_by_name) if contextual_data_by_name else {}

    @property
    def message(self) -> str:
        return self._message

    @property
    def log_event(self) -> LogEventBase:
        return self._log_event

    @property
    @abstractmethod
    def action(self) -> ExceptionAction: ...

    @property
    @abstractmethod
    def reason(self) -> str: ...

    @property
    @abstractmethod
    def http_status_code(self) -> int: ...

    @property
    def severity(self) -> Severity:
        return Severity.ERROR

    @property
    def application_name(self) -> str:
        return self.APPLICATION_NAME

    @property
    def cause(self) -> ExceptionCause | None:
        cause_exception: BaseException | None = self.__cause__
        if cause_exception is None:
            return None
        return ExceptionCause(exception_type=type(cause_exception).__name__, message=str(cause_exception), traceback=cause_exception.__traceback__)

    @property
    def contextual_data_by_name(self) -> ContextualDataDict:
        # Built lazily so overridden properties are read after the descendant's __init__ has run.
        contextual_data: ContextualDataDict = {
            "ApplicationName": self.application_name,
            "ExceptionType": type(self).__name__,
            "Action": self.action.value,
            "Reason": self.reason,
            "LogEvent": self.log_event.value,
            "Severity": self.severity.name,
            "HttpStatusCode": self.http_status_code,
            "Message": self.message,
        }
        contextual_data.update(self._additional_contextual_data_by_name)
        return contextual_data

    def add_contextual_data(self, contextual_data_by_name: ContextualDataDict) -> None:
        self._additional_contextual_data_by_name.update(contextual_data_by_name)

    def to_string(self) -> str:
        """Every contextual value and the cause on its own line, then the traceback, for a log entry."""
        complete_exception_data: ContextualDataDict = self._get_exception_data_with_traceback()

        lines: list[str] = []
        exception_data_name: str
        exception_data_value: str | int | float | bool
        for exception_data_name, exception_data_value in complete_exception_data.items():
            if exception_data_name != self.TRACEBACK_KEY:
                lines.append(f"{exception_data_name}: {exception_data_value}")

        if self.TRACEBACK_KEY in complete_exception_data:
            lines.extend(["", str(complete_exception_data[self.TRACEBACK_KEY])])

        return "\n".join(lines)

    def to_json(self) -> str:
        return json.dumps(self._get_exception_data_with_traceback(), indent=2)

    def _get_exception_data(self) -> ContextualDataDict:
        complete_exception_data: ContextualDataDict = self.contextual_data_by_name

        exception_cause: ExceptionCause | None = self.cause
        if exception_cause:
            complete_exception_data["CausedBy"] = exception_cause.exception_type
            complete_exception_data["Cause"] = exception_cause.message

        return complete_exception_data

    def _get_exception_data_with_traceback(self) -> ContextualDataDict:
        complete_exception_data: ContextualDataDict = self._get_exception_data()
        if self.__traceback__:
            complete_exception_data[self.TRACEBACK_KEY] = "".join(traceback.format_tb(self.__traceback__))
        return complete_exception_data


class VoiceAgentRestaurantBusinessBaseException(VoiceAgentRestaurantBaseException, ABC):
    """The request was understood and refused by a business rule. The caller can act on the message."""

    @property
    @override
    def http_status_code(self) -> int:
        return 400

    @property
    @override
    def action(self) -> ExceptionAction:
        return ExceptionAction.USER_ACTION_REQUIRED


class VoiceAgentRestaurantTechnicalBaseException(VoiceAgentRestaurantBaseException, ABC):
    """Infrastructure or system trouble unrelated to the merit of the request. Its message never reaches a guest."""

    @property
    @override
    def http_status_code(self) -> int:
        return 500


@final
class VoiceAgentRestaurantExceptionJsonEncoder(json.JSONEncoder):
    # Parameter `o` is named this way because json.JSONEncoder.default() defines it as such
    @override
    def default(self, o: object) -> object:
        if isinstance(o, VoiceAgentRestaurantBaseException):
            return o.contextual_data_by_name
        if isinstance(o, ExceptionCause):
            return o.to_dict()
        if isinstance(o, Enum):
            return o.value
        if isinstance(o, datetime | date | time):
            return o.isoformat()
        if isinstance(o, Exception):
            return {"ExceptionType": type(o).__name__, "Message": str(o)}

        return super().default(o)
