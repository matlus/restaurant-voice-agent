import json
from dataclasses import dataclass
from typing import Final

from starlette.responses import JSONResponse, Response

from voice_agent_conversation import (
    VoiceAgentConversationBaseException,
    VoiceAgentConversationBusinessBaseException,
)
from voice_agent_restaurant import VoiceAgentRestaurantBaseException, VoiceAgentRestaurantBusinessBaseException
from voice_agent_web.resource_models.conversation_resources import ConversationErrorMessage
from voice_agent_web.resource_models.problem_details_resources import ProblemDetailsResource


@dataclass(frozen=True)
class WebSocketFailure:
    """What a WebSocket caller is sent when its conversation fails: one error text frame, then the close frame."""

    error_message_text: str
    close_code: int
    close_reason: str


@dataclass(frozen=True)
class _WireFailure:
    http_status_code: int
    title: str
    detail: str
    exception_type: str
    websocket_close_code: int


class ExceptionToWireTranslator:
    """Owns the whole mapping from an escaped exception to what the caller is told, envelope included.

    A business refusal carries its full message, which is written for the guest. A technical failure carries
    only its one-sentence reason. Anything unexpected carries a fixed message and a fixed type that reveal nothing.
    """

    PROBLEM_DETAILS_MEDIA_TYPE: Final[str] = "application/problem+json"
    PROBLEM_DETAILS_TYPE: Final[str] = "about:blank"
    EXCEPTION_TYPE_HEADER_NAME: Final[str] = "exception-type"
    POLICY_VIOLATION_CLOSE_CODE: Final[int] = 1008
    INTERNAL_ERROR_CLOSE_CODE: Final[int] = 1011
    TRY_AGAIN_LATER_CLOSE_CODE: Final[int] = 1013
    SERVICE_UNAVAILABLE_STATUS_CODE: Final[int] = 503
    UNEXPECTED_FAILURE_STATUS_CODE: Final[int] = 500
    UNEXPECTED_FAILURE_TITLE: Final[str] = "Unexpected failure"
    UNEXPECTED_FAILURE_DETAIL: Final[str] = "Something went wrong on our side. Please try again."
    UNEXPECTED_EXCEPTION_TYPE: Final[str] = "UnexpectedException"
    # A WebSocket close frame carries at most 125 payload bytes, two of them the close code, so the reason must fit in 123 UTF-8 bytes.
    MAXIMUM_CLOSE_REASON_BYTE_COUNT: Final[int] = 123

    @classmethod
    def translate_to_problem_details(cls, escaped_exception: BaseException, request_path: str) -> Response:
        wire_failure: _WireFailure = cls._classify(escaped_exception)
        problem_details: ProblemDetailsResource = {
            "type": cls.PROBLEM_DETAILS_TYPE,
            "title": wire_failure.title,
            "status": wire_failure.http_status_code,
            "detail": wire_failure.detail,
            "instance": request_path,
        }
        return JSONResponse(
            content=problem_details,
            status_code=wire_failure.http_status_code,
            media_type=cls.PROBLEM_DETAILS_MEDIA_TYPE,
            headers={cls.EXCEPTION_TYPE_HEADER_NAME: wire_failure.exception_type},
        )

    @classmethod
    def translate_to_websocket_failure(cls, escaped_exception: BaseException) -> WebSocketFailure:
        wire_failure: _WireFailure = cls._classify(escaped_exception)
        conversation_error_message: ConversationErrorMessage = {"type": "error", "title": wire_failure.title, "detail": wire_failure.detail}
        return WebSocketFailure(
            error_message_text=json.dumps(conversation_error_message),
            close_code=wire_failure.websocket_close_code,
            close_reason=wire_failure.title.encode("utf-8")[: cls.MAXIMUM_CLOSE_REASON_BYTE_COUNT].decode("utf-8", errors="ignore"),
        )

    @classmethod
    def _classify(cls, escaped_exception: BaseException) -> _WireFailure:
        if isinstance(escaped_exception, VoiceAgentConversationBusinessBaseException | VoiceAgentRestaurantBusinessBaseException):
            return _WireFailure(
                http_status_code=escaped_exception.http_status_code,
                title=escaped_exception.reason,
                detail=escaped_exception.message,
                exception_type=type(escaped_exception).__name__,
                websocket_close_code=cls.POLICY_VIOLATION_CLOSE_CODE,
            )
        if isinstance(escaped_exception, VoiceAgentConversationBaseException | VoiceAgentRestaurantBaseException):
            return _WireFailure(
                http_status_code=escaped_exception.http_status_code,
                title=escaped_exception.reason,
                detail=escaped_exception.reason,
                exception_type=type(escaped_exception).__name__,
                websocket_close_code=cls.TRY_AGAIN_LATER_CLOSE_CODE
                if escaped_exception.http_status_code == cls.SERVICE_UNAVAILABLE_STATUS_CODE
                else cls.INTERNAL_ERROR_CLOSE_CODE,
            )
        return _WireFailure(
            http_status_code=cls.UNEXPECTED_FAILURE_STATUS_CODE,
            title=cls.UNEXPECTED_FAILURE_TITLE,
            detail=cls.UNEXPECTED_FAILURE_DETAIL,
            exception_type=cls.UNEXPECTED_EXCEPTION_TYPE,
            websocket_close_code=cls.INTERNAL_ERROR_CLOSE_CODE,
        )
