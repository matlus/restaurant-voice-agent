# Class tests for ExceptionToWireTranslator: the whole exception-to-wire contract, proven without hosting anything.
# Each test builds the exact exception, translates it, and compares the complete envelope that comes back: the problem
# details response for HTTP and the error frame and close frame for a WebSocket. The pipeline tests leave this table here.

import json
from dataclasses import dataclass
from typing import Final

import pytest
from starlette.responses import Response
from web_test_support.generated_words import create_generated_word

from voice_agent_conversation import (
    RealtimeVoiceProviderErrorException,
    RealtimeVoiceProviderUnavailableException,
    VoiceAgentConversationBaseException,
    VoiceAgentConversationTechnicalBaseException,
    VoiceNotOfferedException,
)
from voice_agent_conversation.managers.exceptions.conversation_exceptions import LogEventConversation
from voice_agent_conversation.managers.exceptions.realtime_voice_exceptions import LogEventRealtimeVoice
from voice_agent_restaurant import DishNotFoundException, VoiceAgentRestaurantBaseException
from voice_agent_web.middleware.translators.exception_to_wire_translator import ExceptionToWireTranslator, WebSocketFailure

REQUEST_PATH: Final[str] = "/voices"
PROBLEM_DETAILS_MEDIA_TYPE: Final[str] = "application/problem+json"
INTERNAL_DETAIL: Final[str] = "connection reset by realtime-edge-7.internal:443"

type DomainException = VoiceAgentConversationBaseException | VoiceAgentRestaurantBaseException


@dataclass(frozen=True)
class ProblemDetailsEnvelope:
    http_status_code: int
    content_type: str
    exception_type: str
    problem_details: dict[str, object]


def read_problem_details_envelope(problem_details_response: Response) -> ProblemDetailsEnvelope:
    return ProblemDetailsEnvelope(
        http_status_code=problem_details_response.status_code,
        content_type=problem_details_response.headers["content-type"],
        exception_type=problem_details_response.headers[ExceptionToWireTranslator.EXCEPTION_TYPE_HEADER_NAME],
        problem_details=json.loads(bytes(problem_details_response.body)),
    )


def create_websocket_failure(title: str, detail: str, close_code: int) -> WebSocketFailure:
    return WebSocketFailure(
        error_message_text=json.dumps({"type": "error", "title": title, "detail": detail}), close_code=close_code, close_reason=title
    )


class TestExceptionToWireTranslatorBusinessRefusals:
    @pytest.mark.parametrize(
        "business_exception",
        [
            pytest.param(
                VoiceNotOfferedException("openai-nova", ["openai-marin", "openai-ash"], LogEventConversation.CONVERSATION_START),
                id="voice-not-offered",
            ),
            pytest.param(DishNotFoundException(create_generated_word(), [create_generated_word()]), id="restaurant-dish-not-found"),
        ],
    )
    def test_TranslateToProblemDetails_WhenTheExceptionIsABusinessRefusal_ThenTheEnvelopeCarriesItsOwnStatusTypeReasonAndFullMessage(
        self, business_exception: DomainException
    ) -> None:
        expected_problem_details_envelope: ProblemDetailsEnvelope = ProblemDetailsEnvelope(
            http_status_code=business_exception.http_status_code,
            content_type=PROBLEM_DETAILS_MEDIA_TYPE,
            exception_type=type(business_exception).__name__,
            problem_details={
                "type": "about:blank",
                "title": business_exception.reason,
                "status": business_exception.http_status_code,
                "detail": business_exception.message,
                "instance": REQUEST_PATH,
            },
        )

        actual_response: Response = ExceptionToWireTranslator.translate_to_problem_details(business_exception, request_path=REQUEST_PATH)

        assert read_problem_details_envelope(actual_response) == expected_problem_details_envelope

    def test_TranslateToWebSocketFailure_WhenTheExceptionIsABusinessRefusal_ThenTheFrameCarriesTheFullMessageAndTheCloseIsAPolicyViolation(
        self,
    ) -> None:
        voice_not_offered_exception: VoiceNotOfferedException = VoiceNotOfferedException(
            "openai-nova", ["openai-marin"], LogEventConversation.CONVERSATION_START
        )
        expected_websocket_failure: WebSocketFailure = create_websocket_failure(
            title="The requested voice is not offered", detail=voice_not_offered_exception.message, close_code=1008
        )

        actual_websocket_failure: WebSocketFailure = ExceptionToWireTranslator.translate_to_websocket_failure(voice_not_offered_exception)

        assert actual_websocket_failure == expected_websocket_failure


class TestExceptionToWireTranslatorTechnicalFailures:
    @pytest.mark.parametrize(
        ("technical_exception", "expected_close_code"),
        [
            pytest.param(
                RealtimeVoiceProviderUnavailableException(f"Could not reach OpenAI Realtime: {INTERNAL_DETAIL}", LogEventRealtimeVoice.SESSION_OPEN),
                1013,
                id="service-unavailable-503-try-again-later",
            ),
            pytest.param(
                RealtimeVoiceProviderErrorException(f"OpenAI Realtime reported an error: {INTERNAL_DETAIL}", LogEventRealtimeVoice.EVENT_RECEIPT),
                1011,
                id="provider-error-502-internal-error",
            ),
        ],
    )
    def test_TranslateToWebSocketFailure_WhenTheExceptionIsATechnicalFailure_ThenOnlyItsReasonIsToldAndTheCloseCodeFollowsItsStatus(
        self, technical_exception: VoiceAgentConversationTechnicalBaseException, expected_close_code: int
    ) -> None:
        expected_websocket_failure: WebSocketFailure = create_websocket_failure(
            title=technical_exception.reason, detail=technical_exception.reason, close_code=expected_close_code
        )

        actual_websocket_failure: WebSocketFailure = ExceptionToWireTranslator.translate_to_websocket_failure(technical_exception)

        assert (actual_websocket_failure, INTERNAL_DETAIL in actual_websocket_failure.error_message_text) == (expected_websocket_failure, False)

    def test_TranslateToProblemDetails_WhenTheExceptionIsATechnicalFailure_ThenTheDetailIsTheReasonAloneAndTheInternalDetailStaysOut(self) -> None:
        realtime_voice_provider_unavailable_exception: RealtimeVoiceProviderUnavailableException = RealtimeVoiceProviderUnavailableException(
            f"Could not reach OpenAI Realtime: {INTERNAL_DETAIL}", LogEventRealtimeVoice.SESSION_OPEN
        )
        expected_reason: str = "The voice service is temporarily unavailable"
        expected_problem_details_envelope: ProblemDetailsEnvelope = ProblemDetailsEnvelope(
            http_status_code=503,
            content_type=PROBLEM_DETAILS_MEDIA_TYPE,
            exception_type="RealtimeVoiceProviderUnavailableException",
            problem_details={
                "type": "about:blank",
                "title": expected_reason,
                "status": 503,
                "detail": expected_reason,
                "instance": REQUEST_PATH,
            },
        )

        actual_response: Response = ExceptionToWireTranslator.translate_to_problem_details(
            realtime_voice_provider_unavailable_exception, request_path=REQUEST_PATH
        )

        assert (read_problem_details_envelope(actual_response), INTERNAL_DETAIL in bytes(actual_response.body).decode("utf-8")) == (
            expected_problem_details_envelope,
            False,
        )


class TestExceptionToWireTranslatorUnexpectedFailures:
    def test_TranslateToProblemDetails_WhenTheExceptionIsNotADomainException_ThenAFixed500RevealsNeitherItsMessageNorItsType(self) -> None:
        unexpected_exception: KeyError = KeyError(INTERNAL_DETAIL)
        expected_problem_details_envelope: ProblemDetailsEnvelope = ProblemDetailsEnvelope(
            http_status_code=500,
            content_type=PROBLEM_DETAILS_MEDIA_TYPE,
            exception_type=ExceptionToWireTranslator.UNEXPECTED_EXCEPTION_TYPE,
            problem_details={
                "type": "about:blank",
                "title": ExceptionToWireTranslator.UNEXPECTED_FAILURE_TITLE,
                "status": 500,
                "detail": ExceptionToWireTranslator.UNEXPECTED_FAILURE_DETAIL,
                "instance": REQUEST_PATH,
            },
        )

        actual_response: Response = ExceptionToWireTranslator.translate_to_problem_details(unexpected_exception, request_path=REQUEST_PATH)

        actual_response_text: str = bytes(actual_response.body).decode("utf-8") + str(actual_response.headers)
        assert (read_problem_details_envelope(actual_response), INTERNAL_DETAIL in actual_response_text, "KeyError" in actual_response_text) == (
            expected_problem_details_envelope,
            False,
            False,
        )

    def test_TranslateToWebSocketFailure_WhenTheExceptionIsNotADomainException_ThenTheFixedDetailIsToldAndTheCloseIsAnInternalError(self) -> None:
        unexpected_exception: ValueError = ValueError(INTERNAL_DETAIL)
        expected_websocket_failure: WebSocketFailure = create_websocket_failure(
            title=ExceptionToWireTranslator.UNEXPECTED_FAILURE_TITLE, detail=ExceptionToWireTranslator.UNEXPECTED_FAILURE_DETAIL, close_code=1011
        )

        actual_websocket_failure: WebSocketFailure = ExceptionToWireTranslator.translate_to_websocket_failure(unexpected_exception)

        assert actual_websocket_failure == expected_websocket_failure
