from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import datetime, time
from typing import Final
from zoneinfo import ZoneInfo

from voice_agent_restaurant.managers.clocks.clock_base import ClockBase
from voice_agent_restaurant.managers.configuration_providers.settings_models.restaurant_store_settings import RestaurantStoreSettings
from voice_agent_restaurant.managers.data_managers.data_manager_reservations import DataManagerReservations
from voice_agent_restaurant.managers.data_managers.data_manager_restaurant import DataManagerRestaurant
from voice_agent_restaurant.managers.exceptions.reservation_exceptions import (
    CandidateTablesTakenException,
    GuestReservationNotFoundException,
    NoTableAvailableException,
    OutsideSeatingHoursException,
    ReservationAlreadyStartedException,
    RestaurantClosedOnDateException,
)
from voice_agent_restaurant.managers.exceptions.voice_agent_restaurant_exceptions import ContextualDataDict
from voice_agent_restaurant.managers.models.reservation_models import (
    AvailabilityRequest,
    AvailabilityResult,
    BookedSchedule,
    BookingIdentity,
    BookingWindow,
    GuestBookingIdentity,
    GuestBookingSearch,
    NewReservation,
    RequestedSeating,
    Reservation,
    ReservationCancellation,
    ReservationCancellationRequest,
    ReservationChangeRequest,
    ReservationIdentity,
    ReservationRequest,
    ReservationReschedule,
    ReservationSearchRequest,
    Seating,
    ValidatedAvailabilityRequest,
    ValidatedReservationChange,
    ValidatedReservationRequest,
)
from voice_agent_restaurant.managers.models.restaurant_models import (
    Closure,
    DiningTable,
    ReservationPolicy,
    RestaurantProfile,
    Weekday,
    WeekdayHours,
)
from voice_agent_restaurant.managers.rules.guest_name_matching import GuestNameMatching
from voice_agent_restaurant.managers.rules.seating_rules import SeatingDay, SeatingRhythm, SeatingRules, SeatingWindow
from voice_agent_restaurant.managers.service_locators.service_locator_base import ServiceLocatorBase
from voice_agent_restaurant.managers.validators.validator_reservation_requests import ValidatorReservationRequests


@dataclass(frozen=True)
class _BookingContext:
    """The restaurant's booking rules as they apply right now."""

    reservation_policy: ReservationPolicy
    booking_window: BookingWindow
    seating_rhythm: SeatingRhythm


@dataclass(frozen=True)
class _SeatingPlan:
    """Everything decided about seating a request before the store is asked: when, until when, and which tables fit."""

    requested_seating: RequestedSeating
    ends_at: time
    seating_window: SeatingWindow
    fitting_tables: list[DiningTable]
    seating_rhythm: SeatingRhythm
    restaurant_now: datetime


class ManagerReservations:
    """Checks availability and books, finds, changes and cancels reservations.

    Every operation validates what arrived first, then decides whether the restaurant can seat the
    party, then lets the store seat it atomically. A guest finds their bookings only by giving the phone
    number, name and date they booked under. Changes and cancellations find the booking by its confirmation
    code, where a phone number given with it must be the one the booking was made with, or else by the
    phone number, name, date and time it is booked under.
    """

    RESERVATION_DATE_CONTEXT_KEY: Final[str] = "Reservation.Date"

    def __init__(self, service_locator: ServiceLocatorBase) -> None:
        self._clock: ClockBase = service_locator.create_clock()
        restaurant_store_settings: RestaurantStoreSettings = service_locator.get_configuration_provider().get_restaurant_store_settings()
        self._data_manager_restaurant: DataManagerRestaurant = DataManagerRestaurant(
            restaurant_store_settings.database_path, restaurant_store_settings.store_seeding, self._clock
        )
        self._data_manager_reservations: DataManagerReservations = DataManagerReservations(
            restaurant_store_settings.database_path, restaurant_store_settings.store_seeding, self._clock
        )

    async def check_availability(self, availability_request: AvailabilityRequest) -> AvailabilityResult:
        validated_availability_request: ValidatedAvailabilityRequest = ValidatorReservationRequests.validate_availability_request(
            availability_request
        )
        booking_context: _BookingContext = await self._load_booking_context()
        seatable_requested_seating: RequestedSeating = await self._read_as_seatable(validated_availability_request.requested_seating, booking_context)
        ValidatorReservationRequests.validate_requested_seating(
            seatable_requested_seating, booking_context.reservation_policy, booking_context.booking_window
        )
        seating_plan: _SeatingPlan = await self._plan_seating(
            seatable_requested_seating, booking_context.seating_rhythm, booking_context.booking_window.restaurant_now
        )
        day_seatings: list[Seating] = await self._data_manager_reservations.find_seatings_on(seatable_requested_seating.reservation_date)
        # The caller's own booking does not hold its table against a move, and its time is not offered back, as for a change.
        own_reservation: Reservation | None = await self._retrieve_own_reservation_among(
            day_seatings, validated_availability_request.own_confirmation_code
        )
        seatings: list[Seating] = self._leave_out_booking(day_seatings, validated_availability_request.own_confirmation_code)
        table_is_free: bool = SeatingRules.has_free_table(
            seating_plan.fitting_tables, seatings, seatable_requested_seating.starts_at, seating_plan.ends_at
        )
        return AvailabilityResult(
            reservation_date=seatable_requested_seating.reservation_date,
            requested_time=seatable_requested_seating.starts_at,
            party_size=seatable_requested_seating.party_size,
            is_available=table_is_free,
            alternative_times=[]
            if table_is_free
            else self._find_alternative_times(seating_plan, seatings, self._find_kept_time(seatable_requested_seating, own_reservation)),
        )

    async def create_reservation(self, reservation_request: ReservationRequest) -> Reservation:
        stated_validated_reservation_request: ValidatedReservationRequest = ValidatorReservationRequests.validate_reservation_request(
            reservation_request
        )
        booking_context: _BookingContext = await self._load_booking_context()
        seatable_validated_reservation_request: ValidatedReservationRequest = replace(
            stated_validated_reservation_request,
            requested_seating=await self._read_as_seatable(stated_validated_reservation_request.requested_seating, booking_context),
        )
        ValidatorReservationRequests.validate_requested_seating(
            seatable_validated_reservation_request.requested_seating, booking_context.reservation_policy, booking_context.booking_window
        )
        seating_plan: _SeatingPlan = await self._plan_seating(
            seatable_validated_reservation_request.requested_seating, booking_context.seating_rhythm, booking_context.booking_window.restaurant_now
        )
        new_reservation: NewReservation = self._to_new_reservation(seatable_validated_reservation_request, seating_plan.ends_at)
        try:
            reservation: Reservation = await self._data_manager_reservations.record_reservation(
                new_reservation, SeatingRules.get_candidate_table_ids(seating_plan.fitting_tables), self._clock.now_utc()
            )
        except CandidateTablesTakenException as candidate_tables_taken_exception:
            raise await self._create_no_table_exception(seating_plan, None) from candidate_tables_taken_exception
        return reservation

    async def find_reservations(self, reservation_search_request: ReservationSearchRequest) -> list[Reservation]:
        guest_booking_search: GuestBookingSearch = ValidatorReservationRequests.validate_search_request(reservation_search_request)
        restaurant_now: datetime = await self._get_restaurant_now()
        booked_reservations: list[Reservation] = await self._data_manager_reservations.find_booked_reservations_on(
            guest_booking_search.phone_number, guest_booking_search.reservation_date
        )
        return self._select_guest_reservations(booked_reservations, guest_booking_search.guest_name, restaurant_now)

    async def change_reservation(self, reservation_change_request: ReservationChangeRequest) -> Reservation:
        validated_reservation_change: ValidatedReservationChange = ValidatorReservationRequests.validate_change_request(reservation_change_request)
        booking_context: _BookingContext = await self._load_booking_context()
        current_reservation: Reservation = await self._retrieve_changeable_reservation(
            validated_reservation_change.booking_identity,
            booking_context.booking_window.restaurant_now,
            booking_context.seating_rhythm.seating_duration_minutes,
        )
        current_requested_seating: RequestedSeating = self._to_current_requested_seating(current_reservation)
        stated_changed_requested_seating: RequestedSeating = SeatingRules.apply_seating_change(
            current_requested_seating, validated_reservation_change.seating_change
        )
        # Only a time the caller says now is read as callers say it; a kept time is already the booked one.
        changed_requested_seating: RequestedSeating = (
            stated_changed_requested_seating
            if validated_reservation_change.seating_change.starts_at is None
            else await self._read_as_seatable(stated_changed_requested_seating, booking_context)
        )
        ValidatorReservationRequests.validate_changed_seating(
            current_requested_seating, changed_requested_seating, booking_context.reservation_policy, booking_context.booking_window
        )
        seating_plan: _SeatingPlan = await self._plan_seating(
            changed_requested_seating, booking_context.seating_rhythm, booking_context.booking_window.restaurant_now
        )
        reservation_reschedule: ReservationReschedule = self._to_reservation_reschedule(
            current_reservation, validated_reservation_change, changed_requested_seating, seating_plan.ends_at
        )
        candidate_table_ids: list[str] = SeatingRules.get_candidate_table_ids_keeping_current(
            seating_plan.fitting_tables, current_reservation.table_id
        )
        try:
            changed_reservation: Reservation = await self._data_manager_reservations.reschedule_reservation(
                reservation_reschedule, candidate_table_ids, self._clock.now_utc()
            )
        except CandidateTablesTakenException as candidate_tables_taken_exception:
            raise await self._create_no_table_exception(seating_plan, current_reservation) from candidate_tables_taken_exception
        return changed_reservation

    async def cancel_reservation(self, reservation_cancellation_request: ReservationCancellationRequest) -> Reservation:
        booking_identity: BookingIdentity = ValidatorReservationRequests.validate_cancellation_request(reservation_cancellation_request)
        booking_context: _BookingContext = await self._load_booking_context()
        current_reservation: Reservation = await self._retrieve_changeable_reservation(
            booking_identity, booking_context.booking_window.restaurant_now, booking_context.seating_rhythm.seating_duration_minutes
        )
        return await self._data_manager_reservations.cancel_reservation(
            ReservationCancellation(
                confirmation_code=current_reservation.confirmation_code, current_booked_schedule=self._to_booked_schedule(current_reservation)
            ),
            self._clock.now_utc(),
        )

    async def _load_booking_context(self) -> _BookingContext:
        restaurant_profile: RestaurantProfile = await self._data_manager_restaurant.get_restaurant_profile()
        reservation_policy: ReservationPolicy = restaurant_profile.reservation_policy
        restaurant_now: datetime = self._to_restaurant_now(restaurant_profile.time_zone)
        return _BookingContext(
            reservation_policy=reservation_policy,
            booking_window=SeatingRules.get_booking_window(restaurant_now, reservation_policy.booking_window_days),
            seating_rhythm=SeatingRhythm(
                slot_interval_minutes=reservation_policy.slot_interval_minutes, seating_duration_minutes=reservation_policy.seating_duration_minutes
            ),
        )

    async def _get_restaurant_now(self) -> datetime:
        restaurant_profile: RestaurantProfile = await self._data_manager_restaurant.get_restaurant_profile()
        return self._to_restaurant_now(restaurant_profile.time_zone)

    async def _retrieve_changeable_reservation(
        self, booking_identity: BookingIdentity, restaurant_now: datetime, seating_duration_minutes: int
    ) -> Reservation:
        current_reservation: Reservation = (
            await self._data_manager_reservations.retrieve_booked_reservation(booking_identity)
            if isinstance(booking_identity, ReservationIdentity)
            else await self._retrieve_guest_reservation(booking_identity, restaurant_now, seating_duration_minutes)
        )
        if SeatingRules.has_started(current_reservation.reservation_date, current_reservation.starts_at, restaurant_now):
            raise ReservationAlreadyStartedException(
                current_reservation.confirmation_code,
                {
                    "Reservation.ConfirmationCode": current_reservation.confirmation_code,
                    self.RESERVATION_DATE_CONTEXT_KEY: current_reservation.reservation_date.isoformat(),
                    "Reservation.StartsAt": f"{current_reservation.starts_at:%H:%M}",
                    "Restaurant.LocalNow": restaurant_now.isoformat(timespec="minutes"),
                },
            )
        return current_reservation

    async def _retrieve_guest_reservation(
        self, guest_booking_identity: GuestBookingIdentity, restaurant_now: datetime, seating_duration_minutes: int
    ) -> Reservation:
        guest_booking_search: GuestBookingSearch = guest_booking_identity.guest_booking_search
        # The time is read as callers say it, as for a new booking, so "7:00" finds a 19:00 dinner booking.
        booked_starts_at: time = SeatingRules.read_as_seatable_time_on(
            await self._data_manager_restaurant.retrieve_weekday_hours(SeatingRules.weekday_of(guest_booking_search.reservation_date)),
            guest_booking_identity.starts_at,
            seating_duration_minutes,
        )
        booked_reservations: list[Reservation] = await self._data_manager_reservations.find_booked_reservations_on(
            guest_booking_search.phone_number, guest_booking_search.reservation_date
        )
        guest_reservations: list[Reservation] = self._select_guest_reservations_at(
            booked_reservations, guest_booking_search.guest_name, booked_starts_at, restaurant_now
        )
        if len(guest_reservations) != 1:
            # Two bookings under one name and number at one time cannot be told apart; the guest needs the code for either.
            raise GuestReservationNotFoundException(
                guest_booking_search.reservation_date,
                booked_starts_at,
                {
                    self.RESERVATION_DATE_CONTEXT_KEY: guest_booking_search.reservation_date.isoformat(),
                    "Reservation.MatchingBookingCount": len(guest_reservations),
                },
            )
        return guest_reservations[0]

    async def _read_as_seatable(self, stated_requested_seating: RequestedSeating, booking_context: _BookingContext) -> RequestedSeating:
        # Resolved before any other check, so a dinner time said without PM is not refused as already passed or too early.
        weekday_hours: WeekdayHours = await self._data_manager_restaurant.retrieve_weekday_hours(
            SeatingRules.weekday_of(stated_requested_seating.reservation_date)
        )
        return replace(
            stated_requested_seating,
            starts_at=SeatingRules.read_as_seatable_time_on(
                weekday_hours, stated_requested_seating.starts_at, booking_context.seating_rhythm.seating_duration_minutes
            ),
        )

    async def _plan_seating(self, requested_seating: RequestedSeating, seating_rhythm: SeatingRhythm, restaurant_now: datetime) -> _SeatingPlan:
        seating_window: SeatingWindow = await self._get_seating_window_or_refuse(requested_seating, seating_rhythm.seating_duration_minutes)
        dining_tables: list[DiningTable] = await self._data_manager_restaurant.get_dining_tables()
        return _SeatingPlan(
            requested_seating=requested_seating,
            ends_at=SeatingRules.get_ends_at(requested_seating.starts_at, seating_rhythm.seating_duration_minutes),
            seating_window=seating_window,
            fitting_tables=SeatingRules.get_fitting_tables(dining_tables, requested_seating.party_size),
            seating_rhythm=seating_rhythm,
            restaurant_now=restaurant_now,
        )

    async def _get_seating_window_or_refuse(self, requested_seating: RequestedSeating, seating_duration_minutes: int) -> SeatingWindow:
        contextual_data_by_name: ContextualDataDict = {self.RESERVATION_DATE_CONTEXT_KEY: requested_seating.reservation_date.isoformat()}
        closures: list[Closure] = await self._data_manager_restaurant.find_closures_between(
            requested_seating.reservation_date, requested_seating.reservation_date
        )
        if closures:
            raise RestaurantClosedOnDateException(requested_seating.reservation_date, closures[0].reason, contextual_data_by_name)

        requested_weekday: Weekday = SeatingRules.weekday_of(requested_seating.reservation_date)
        weekday_hours: WeekdayHours = await self._data_manager_restaurant.retrieve_weekday_hours(requested_weekday)
        seating_window: SeatingWindow | None = SeatingRules.get_seating_window(weekday_hours, seating_duration_minutes)
        if seating_window is None:
            raise RestaurantClosedOnDateException(
                requested_seating.reservation_date, f"closed on {requested_weekday.value.capitalize()}s", contextual_data_by_name
            )
        if not SeatingRules.is_within_window(requested_seating.starts_at, seating_window):
            raise OutsideSeatingHoursException(
                requested_seating.reservation_date,
                requested_seating.starts_at,
                seating_window.first_seating_time,
                seating_window.last_seating_time,
                contextual_data_by_name,
            )
        return seating_window

    async def _create_no_table_exception(self, seating_plan: _SeatingPlan, current_reservation: Reservation | None) -> NoTableAvailableException:
        # A booking being changed never blocks its own alternatives, and the time it already holds is not offered as one.
        seatings: list[Seating] = self._leave_out_booking(
            await self._data_manager_reservations.find_seatings_on(seating_plan.requested_seating.reservation_date),
            None if current_reservation is None else current_reservation.confirmation_code,
        )
        return NoTableAvailableException(
            requested_date=seating_plan.requested_seating.reservation_date,
            requested_time=seating_plan.requested_seating.starts_at,
            party_size=seating_plan.requested_seating.party_size,
            alternative_times=self._find_alternative_times(
                seating_plan, seatings, self._find_kept_time(seating_plan.requested_seating, current_reservation)
            ),
            contextual_data_by_name={
                self.RESERVATION_DATE_CONTEXT_KEY: seating_plan.requested_seating.reservation_date.isoformat(),
                "Reservation.PartySize": seating_plan.requested_seating.party_size,
            },
        )

    async def _retrieve_own_reservation_among(self, day_seatings: Iterable[Seating], own_confirmation_code: str | None) -> Reservation | None:
        """The caller's own booking, when it holds a table that day. A code for no booking that day changes nothing, so it is
        not looked up and does not reveal whether such a booking exists."""
        if own_confirmation_code is None or all(seating.confirmation_code != own_confirmation_code for seating in day_seatings):
            return None
        return await self._data_manager_reservations.retrieve_booked_reservation(
            ReservationIdentity(confirmation_code=own_confirmation_code, phone_number=None)
        )

    @staticmethod
    def _leave_out_booking(seatings: Iterable[Seating], left_out_confirmation_code: str | None) -> list[Seating]:
        return [seating for seating in seatings if seating.confirmation_code != left_out_confirmation_code]

    @staticmethod
    def _find_kept_time(requested_seating: RequestedSeating, current_reservation: Reservation | None) -> time | None:
        """The time the booking being moved already holds, when the move asks for the same party on the same day. For a
        different day or party size that time is a real alternative, so it is not held back."""
        if current_reservation is None:
            return None
        requested_seating_keeps_party_and_day: bool = (
            requested_seating.reservation_date == current_reservation.reservation_date
            and requested_seating.party_size == current_reservation.party_size
        )
        return current_reservation.starts_at if requested_seating_keeps_party_and_day else None

    @staticmethod
    def _find_alternative_times(seating_plan: _SeatingPlan, seatings: list[Seating], kept_time: time | None) -> list[time]:
        seating_day: SeatingDay = SeatingDay(
            reservation_date=seating_plan.requested_seating.reservation_date,
            seating_window=seating_plan.seating_window,
            fitting_tables=seating_plan.fitting_tables,
            seatings=seatings,
            kept_time=kept_time,
        )
        return SeatingRules.get_alternative_times(
            seating_day, seating_plan.requested_seating.starts_at, seating_plan.seating_rhythm, seating_plan.restaurant_now
        )

    @staticmethod
    def _to_new_reservation(validated_reservation_request: ValidatedReservationRequest, ends_at: time) -> NewReservation:
        return NewReservation(
            guest_name=validated_reservation_request.guest_name,
            phone_number=validated_reservation_request.phone_number,
            party_size=validated_reservation_request.requested_seating.party_size,
            reservation_date=validated_reservation_request.requested_seating.reservation_date,
            starts_at=validated_reservation_request.requested_seating.starts_at,
            ends_at=ends_at,
            notes=validated_reservation_request.notes,
        )

    @staticmethod
    def _to_current_requested_seating(current_reservation: Reservation) -> RequestedSeating:
        return RequestedSeating(
            reservation_date=current_reservation.reservation_date, starts_at=current_reservation.starts_at, party_size=current_reservation.party_size
        )

    @staticmethod
    def _to_reservation_reschedule(
        current_reservation: Reservation,
        validated_reservation_change: ValidatedReservationChange,
        changed_requested_seating: RequestedSeating,
        ends_at: time,
    ) -> ReservationReschedule:
        return ReservationReschedule(
            confirmation_code=current_reservation.confirmation_code,
            current_booked_schedule=ManagerReservations._to_booked_schedule(current_reservation),
            party_size=changed_requested_seating.party_size,
            reservation_date=changed_requested_seating.reservation_date,
            starts_at=changed_requested_seating.starts_at,
            ends_at=ends_at,
            notes=current_reservation.notes if validated_reservation_change.notes is None else validated_reservation_change.notes,
        )

    @staticmethod
    def _select_guest_reservations(booked_reservations: Iterable[Reservation], given_guest_name: str, restaurant_now: datetime) -> list[Reservation]:
        return [
            booked_reservation
            for booked_reservation in booked_reservations
            if GuestNameMatching.is_name_on_booking(booked_reservation.guest_name, given_guest_name)
            and SeatingRules.is_still_upcoming(booked_reservation.reservation_date, booked_reservation.ends_at, restaurant_now)
        ]

    @classmethod
    def _select_guest_reservations_at(
        cls, booked_reservations: Iterable[Reservation], given_guest_name: str, booked_starts_at: time, restaurant_now: datetime
    ) -> list[Reservation]:
        return [
            guest_reservation
            for guest_reservation in cls._select_guest_reservations(booked_reservations, given_guest_name, restaurant_now)
            if guest_reservation.starts_at == booked_starts_at
        ]

    @staticmethod
    def _to_booked_schedule(current_reservation: Reservation) -> BookedSchedule:
        return BookedSchedule(
            party_size=current_reservation.party_size,
            reservation_date=current_reservation.reservation_date,
            starts_at=current_reservation.starts_at,
            ends_at=current_reservation.ends_at,
            table_id=current_reservation.table_id,
            notes=current_reservation.notes,
        )

    def _to_restaurant_now(self, time_zone: str) -> datetime:
        return self._clock.now_utc().astimezone(ZoneInfo(time_zone))
