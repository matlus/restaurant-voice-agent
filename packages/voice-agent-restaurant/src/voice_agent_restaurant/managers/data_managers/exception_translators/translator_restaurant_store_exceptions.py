from voice_agent_restaurant.managers.exceptions.restaurant_store_exceptions import RestaurantStoreUnavailableException
from voice_agent_restaurant.managers.exceptions.voice_agent_restaurant_exceptions import ContextualDataDict


class TranslatorRestaurantStoreExceptions:
    """Translates native SQLite and file-system failures into the domain's store exception.

    Every write commits as its last statement inside the translated scope, so a failure caught here never follows a
    committed change: the operation did not take effect.
    """

    @staticmethod
    def translate(
        store_error: Exception, operation_description: str, contextual_data_by_name: ContextualDataDict | None = None
    ) -> RestaurantStoreUnavailableException:
        complete_contextual_data_by_name: ContextualDataDict = {
            "RestaurantStore.Operation": operation_description,
            "RestaurantStore.ErrorType": type(store_error).__name__,
            "RestaurantStore.Error": str(store_error),
        }
        if contextual_data_by_name:
            complete_contextual_data_by_name.update(contextual_data_by_name)
        return RestaurantStoreUnavailableException(
            message=(
                f"The restaurant store could not {operation_description}; this is a temporary problem and the request was not judged on its merits"
            ),
            contextual_data_by_name=complete_contextual_data_by_name,
        )
