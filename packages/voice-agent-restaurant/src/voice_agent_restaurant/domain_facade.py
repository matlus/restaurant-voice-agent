from datetime import datetime
from types import TracebackType
from typing import Self

from voice_agent_restaurant.managers.manager_reservations import ManagerReservations
from voice_agent_restaurant.managers.manager_restaurant import ManagerRestaurant
from voice_agent_restaurant.managers.models.menu_models import Dish, DishLookupRequest, MenuSearchRequest
from voice_agent_restaurant.managers.models.reservation_models import (
    AvailabilityRequest,
    AvailabilityResult,
    Reservation,
    ReservationCancellationRequest,
    ReservationChangeRequest,
    ReservationRequest,
    ReservationSearchRequest,
)
from voice_agent_restaurant.managers.models.restaurant_models import OpeningHours, RestaurantProfile
from voice_agent_restaurant.managers.service_locators.service_locator_base import ServiceLocatorBase
from voice_agent_restaurant.managers.service_locators.service_locator_production import ServiceLocatorProduction


class DomainFacade:
    """The single public entry point to the restaurant: its profile, hours, menu and reservations.

    Business refusals raise VoiceAgentRestaurantBusinessBaseException descendants whose messages can be
    relayed to a guest. Store and configuration trouble raises technical exceptions that must not be.
    The facade owns nothing that needs closing today; close() exists so hosts manage its lifetime the
    same way whatever it comes to own.
    """

    def __init__(self, service_locator: ServiceLocatorBase | None = None) -> None:
        if service_locator is None:
            service_locator = ServiceLocatorProduction()
        self._manager_restaurant: ManagerRestaurant = ManagerRestaurant(service_locator)
        self._manager_reservations: ManagerReservations = ManagerReservations(service_locator)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: TracebackType | None) -> None:
        await self.close()

    async def close(self) -> None:
        """Nothing to release yet; see the class description."""

    async def get_restaurant_profile(self) -> RestaurantProfile:
        return await self._manager_restaurant.get_restaurant_profile()

    async def get_restaurant_local_now(self) -> datetime:
        """The current date and time in the restaurant's own time zone, for resolving phrases like "this Friday"."""
        return await self._manager_restaurant.get_restaurant_local_now()

    async def get_opening_hours(self) -> OpeningHours:
        return await self._manager_restaurant.get_opening_hours()

    async def search_menu(self, menu_search_request: MenuSearchRequest) -> list[Dish]:
        """Returns every dish that suits all the requested diets, contains none of the excluded allergens, and
        matches the optional category, calorie ceiling and text. An empty list means nothing matches."""
        return await self._manager_restaurant.search_menu(menu_search_request)

    async def retrieve_dish(self, dish_lookup_request: DishLookupRequest) -> Dish:
        """Finds one dish by its name or a distinctive part of it. Raises DishNotFoundException naming close matches otherwise."""
        return await self._manager_restaurant.retrieve_dish(dish_lookup_request)

    async def check_availability(self, availability_request: AvailabilityRequest) -> AvailabilityResult:
        """Says whether a table fits the party at the requested time, and offers nearby open times when it does not."""
        return await self._manager_reservations.check_availability(availability_request)

    async def create_reservation(self, reservation_request: ReservationRequest) -> Reservation:
        """Books the smallest free table that fits the party. Raises NoTableAvailableException, naming nearby open times, when none is free."""
        return await self._manager_reservations.create_reservation(reservation_request)

    async def find_reservations(self, reservation_search_request: ReservationSearchRequest) -> list[Reservation]:
        """Returns the upcoming booked reservations made with the phone number, soonest first."""
        return await self._manager_reservations.find_reservations(reservation_search_request)

    async def change_reservation(self, reservation_change_request: ReservationChangeRequest) -> Reservation:
        """Changes the date, time, party size or notes of a booking found by its confirmation code."""
        return await self._manager_reservations.change_reservation(reservation_change_request)

    async def cancel_reservation(self, reservation_cancellation_request: ReservationCancellationRequest) -> Reservation:
        """Cancels a booking found by its confirmation code, returning it in its cancelled state."""
        return await self._manager_reservations.cancel_reservation(reservation_cancellation_request)
