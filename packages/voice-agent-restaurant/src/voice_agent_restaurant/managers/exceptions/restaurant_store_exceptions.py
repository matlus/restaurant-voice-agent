from typing import final, override

from voice_agent_restaurant.managers.exceptions.voice_agent_restaurant_exceptions import (
    ContextualDataDict,
    ExceptionAction,
    LogEventBase,
    VoiceAgentRestaurantTechnicalBaseException,
)


class LogEventRestaurantStore(LogEventBase):
    RESTAURANT_STORE_INITIALIZATION = "RestaurantStoreInitialization"
    RESTAURANT_STORE_OPERATION = "RestaurantStoreOperation"


@final
class RestaurantStoreUnavailableException(VoiceAgentRestaurantTechnicalBaseException):
    """The restaurant store could not complete an operation. Nothing about the request itself was judged."""

    def __init__(self, message: str, contextual_data_by_name: ContextualDataDict | None = None) -> None:
        super().__init__(
            message=message, log_event=LogEventRestaurantStore.RESTAURANT_STORE_OPERATION, contextual_data_by_name=contextual_data_by_name
        )

    @property
    @override
    def action(self) -> ExceptionAction:
        return ExceptionAction.RETRY_ACTION_NEEDED

    @property
    @override
    def reason(self) -> str:
        return "The restaurant store could not complete the operation; this is a temporary problem, not a refusal of the request"


@final
class RestaurantSeedDataInvalidException(VoiceAgentRestaurantTechnicalBaseException):
    """A bundled seed file is missing a value or holds one of the wrong shape. Raised while the store is first created."""

    def __init__(self, message: str, contextual_data_by_name: ContextualDataDict | None = None) -> None:
        super().__init__(
            message=message, log_event=LogEventRestaurantStore.RESTAURANT_STORE_INITIALIZATION, contextual_data_by_name=contextual_data_by_name
        )

    @property
    @override
    def action(self) -> ExceptionAction:
        return ExceptionAction.DEVELOPER_ACTION_REQUIRED

    @property
    @override
    def reason(self) -> str:
        return "The restaurant seed data is invalid"


@final
class RestaurantStoreContractViolationException(VoiceAgentRestaurantTechnicalBaseException):
    """The store holds data the domain relies on being there, or being one way, and it is not: a missing row or an impossible value."""

    def __init__(self, message: str, contextual_data_by_name: ContextualDataDict | None = None) -> None:
        super().__init__(
            message=message, log_event=LogEventRestaurantStore.RESTAURANT_STORE_OPERATION, contextual_data_by_name=contextual_data_by_name
        )

    @property
    @override
    def action(self) -> ExceptionAction:
        return ExceptionAction.DEVELOPER_ACTION_REQUIRED

    @property
    @override
    def reason(self) -> str:
        return "The restaurant store breaks a contract the domain relies on"
