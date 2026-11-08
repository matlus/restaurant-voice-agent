import sqlite3
from typing import Final

from voice_agent_restaurant.managers.exceptions.restaurant_store_exceptions import (
    RestaurantStoreContractViolationException,
    RestaurantStoreUnavailableException,
)
from voice_agent_restaurant.managers.exceptions.voice_agent_restaurant_exceptions import (
    ContextualDataDict,
    VoiceAgentRestaurantTechnicalBaseException,
)


class TranslatorRestaurantStoreExceptions:
    """Translates native SQLite and file-system failures into the domain's store exceptions.

    A busy or locked store, a failing disk read or write, and a file-system error on the database file are temporary:
    the same request can succeed when retried. Every other SQLite failure (a file that is not a SQLite database, a
    missing table, a broken constraint) fails the same way on every retry, so it is reported as a broken contract.

    Every write commits as its last statement inside the translated scope, so a failure caught here never follows a
    committed change: the operation did not take effect.
    """

    # SQLite extended result codes carry the primary result code in their low byte.
    _PRIMARY_RESULT_CODE_MASK: Final[int] = 0xFF
    _TRANSIENT_PRIMARY_RESULT_CODES: Final[frozenset[int]] = frozenset({sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED, sqlite3.SQLITE_IOERR})

    @classmethod
    def translate(
        cls, store_error: Exception, operation_description: str, contextual_data_by_name: ContextualDataDict | None = None
    ) -> VoiceAgentRestaurantTechnicalBaseException:
        complete_contextual_data_by_name: ContextualDataDict = {
            "RestaurantStore.Operation": operation_description,
            "RestaurantStore.ErrorType": type(store_error).__name__,
            "RestaurantStore.Error": str(store_error),
        }
        if contextual_data_by_name:
            complete_contextual_data_by_name.update(contextual_data_by_name)
        if cls._is_transient(store_error):
            return RestaurantStoreUnavailableException(
                message=(
                    f"The restaurant store could not {operation_description}; "
                    "this is a temporary problem and the request was not judged on its merits"
                ),
                contextual_data_by_name=complete_contextual_data_by_name,
            )
        return RestaurantStoreContractViolationException(
            message=(
                f"The restaurant store could not {operation_description} because the store file cannot serve this domain "
                f"({type(store_error).__name__}: {store_error}); retrying will not help"
            ),
            contextual_data_by_name=complete_contextual_data_by_name,
        )

    @classmethod
    def _is_transient(cls, store_error: Exception) -> bool:
        if isinstance(store_error, sqlite3.Error):
            sqlite_error_code: int | None = getattr(store_error, "sqlite_errorcode", None)
            return sqlite_error_code is not None and (sqlite_error_code & cls._PRIMARY_RESULT_CODE_MASK) in cls._TRANSIENT_PRIMARY_RESULT_CODES
        return isinstance(store_error, OSError)
