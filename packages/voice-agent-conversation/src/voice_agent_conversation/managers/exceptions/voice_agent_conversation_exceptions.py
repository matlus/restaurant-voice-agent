import traceback
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum, IntEnum
from typing import Final, override

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


class VoiceAgentConversationBaseException(Exception, ABC):
    """Application base exception for voice conversations.

    Abstract, as are its business and technical descendants. Only problem-specific
    leaf exceptions are raised, each from one place in the system.
    """

    APPLICATION_NAME: Final[str] = "VoiceAgentConversation"

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
        return ExceptionCause(exception_type=type(cause_exception).__name__, message=str(cause_exception))

    @property
    def contextual_data_by_name(self) -> ContextualDataDict:
        # Built lazily so overridden properties are read after the descendant's __init__ has run.
        contextual_data_by_name: ContextualDataDict = {
            "ApplicationName": self.application_name,
            "ExceptionType": type(self).__name__,
            "Action": self.action.value,
            "Reason": self.reason,
            "LogEvent": self.log_event.value,
            "Severity": self.severity.name,
            "HttpStatusCode": self.http_status_code,
            "Message": self.message,
        }
        contextual_data_by_name.update(self._additional_contextual_data_by_name)
        return contextual_data_by_name

    def add_contextual_data(self, contextual_data_by_name: ContextualDataDict) -> None:
        self._additional_contextual_data_by_name.update(contextual_data_by_name)

    def to_string(self) -> str:
        """Every contextual value and the cause on its own line, then the traceback, for a log entry."""
        lines: list[str] = []
        contextual_data_name: str
        contextual_data_value: str | int | float | bool
        for contextual_data_name, contextual_data_value in self.contextual_data_by_name.items():
            lines.append(f"{contextual_data_name}: {contextual_data_value}")

        exception_cause: ExceptionCause | None = self.cause
        if exception_cause:
            lines.append(f"CausedBy: {exception_cause.exception_type}")
            lines.append(f"Cause: {exception_cause.message}")

        if self.__traceback__:
            lines.extend(["", "".join(traceback.format_tb(self.__traceback__))])

        return "\n".join(lines)


class VoiceAgentConversationBusinessBaseException(VoiceAgentConversationBaseException, ABC):
    """The request was understood and refused by a business rule. The caller can act on the message."""

    @property
    @override
    def http_status_code(self) -> int:
        return 400

    @property
    @override
    def action(self) -> ExceptionAction:
        return ExceptionAction.USER_ACTION_REQUIRED


class VoiceAgentConversationTechnicalBaseException(VoiceAgentConversationBaseException, ABC):
    """Infrastructure or system trouble unrelated to the merit of the request. Its message never reaches a guest."""

    @property
    @override
    def http_status_code(self) -> int:
        return 500
