from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
from typing import Final
from zoneinfo import ZoneInfo

from voice_agent_restaurant.managers.clocks.clock_base import ClockBase
from voice_agent_restaurant.managers.data_managers.data_manager_reservations import DataManagerReservations
from voice_agent_restaurant.managers.data_managers.data_manager_restaurant import DataManagerRestaurant
from voice_agent_restaurant.managers.exceptions.reservation_exceptions import (
    CandidateTablesTakenException,
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
    BookingWindow,
    NewReservation,
    RequestedSeating,
    Reservation,
    ReservationCancellationRequest,
    ReservationChangeRequest,
    ReservationIdentity,
    ReservationRequest,
    ReservationReschedule,
    ReservationSearchRequest,
    Seating,
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
    earliest_start: datetime


class ManagerReservations:
    """Checks availability and books, finds, changes and cancels reservations.

    Every operation validates what arrived first, then decides whether the restaurant can seat the
    party, then lets the store seat it atomically. Changes and cancellations require the confirmation
    code and the phone number the booking was made with.
    """

    RESERVATION_DATE_CONTEXT_KEY: Final[str] = "Reservation.Date"

    def __init__(self, service_locator: ServiceLocatorBase) -> None:
        self._clock: ClockBase = service_locator.create_clock()
        database_path: Path = service_locator.get_configuration_provider().get_restaurant_store_settings().database_path
        self._data_manager_restaurant: DataManagerRestaurant = DataManagerRestaurant(database_path, self._clock)
        self._data_manager_reservations: DataManagerReservations = DataManagerReservations(database_path, self._clock)

    async def check_availability(self, availability_request: AvailabilityRequest) -> AvailabilityResult:
        requested_seating: RequestedSeating = ValidatorReservationRequests.validate_availability_request(availability_request)
        booking_context: _BookingContext = await self._load_booking_context()
        ValidatorReservationRequests.validate_requested_seating(requested_seating, booking_context.reservation_policy, booking_context.booking_window)
        seating_plan: _SeatingPlan = await self._plan_seating(requested_seating, booking_context)
        seatings: list[Seating] = await self._data_manager_reservations.find_seatings_on(requested_seating.reservation_date)
        table_is_free: bool = SeatingRules.has_free_table(seating_plan.fitting_tables, seatings, requested_seating.starts_at, seating_plan.ends_at)
        return AvailabilityResult(
            reservation_date=requested_seating.reservation_date,
            requested_time=requested_seating.starts_at,
            party_size=requested_seating.party_size,
            is_available=table_is_free,
            alternative_times=[] if table_is_free else self._find_alternative_times(seating_plan, seatings),
        )

    async def create_reservation(self, reservation_request: ReservationRequest) -> Reservation:
        validated_reservation_request: ValidatedReservationRequest = ValidatorReservationRequests.validate_reservation_request(reservation_request)
        booking_context: _BookingContext = await self._load_booking_context()
        ValidatorReservationRequests.validate_requested_seating(
            validated_reservation_request.requested_seating, booking_context.reservation_policy, booking_context.booking_window
        )
        seating_plan: _SeatingPlan = await self._plan_seating(validated_reservation_request.requested_seating, booking_context)
        new_reservation: NewReservation = self._to_new_reservation(validated_reservation_request, seating_plan.ends_at)
        try:
            reservation: Reservation = await self._data_manager_reservations.record_reservation(
                new_reservation, [fitting_table.table_id for fitting_table in seating_plan.fitting_tables], self._clock.now_utc()
            )
        except CandidateTablesTakenException as candidate_tables_taken_exception:
            raise await self._create_no_table_exception(seating_plan, None) from candidate_tables_taken_exception
        return reservation

    async def find_reservations(self, reservation_search_request: ReservationSearchRequest) -> list[Reservation]:
        phone_number: str = ValidatorReservationRequests.validate_search_request(reservation_search_request)
        restaurant_now: datetime = await self._get_restaurant_now()
        booked_reservations: list[Reservation] = await self._data_manager_reservations.find_booked_reservations(phone_number, restaurant_now.date())
        return [
            booked_reservation
            for booked_reservation in booked_reservations
            if SeatingRules.is_still_upcoming(booked_reservation.reservation_date, booked_reservation.ends_at, restaurant_now)
        ]

    async def change_reservation(self, reservation_change_request: ReservationChangeRequest) -> Reservation:
        validated_reservation_change: ValidatedReservationChange = ValidatorReservationRequests.validate_change_request(reservation_change_request)
        booking_context: _BookingContext = await self._load_booking_context()
        current_reservation: Reservation = await self._retrieve_changeable_reservation(
            validated_reservation_change.reservation_identity, booking_context.booking_window.restaurant_now
        )
        changed_requested_seating: RequestedSeating = SeatingRules.apply_seating_change(
            self._to_current_seating(current_reservation), validated_reservation_change.seating_change
        )
        ValidatorReservationRequests.validate_requested_seating(
            changed_requested_seating, booking_context.reservation_policy, booking_context.booking_window
        )
        seating_plan: _SeatingPlan = await self._plan_seating(changed_requested_seating, booking_context)
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
            raise await self._create_no_table_exception(seating_plan, current_reservation.confirmation_code) from candidate_tables_taken_exception
        return changed_reservation

    async def cancel_reservation(self, reservation_cancellation_request: ReservationCancellationRequest) -> Reservation:
        reservation_identity: ReservationIdentity = ValidatorReservationRequests.validate_cancellation_request(reservation_cancellation_request)
        restaurant_now: datetime = await self._get_restaurant_now()
        current_reservation: Reservation = await self._retrieve_changeable_reservation(reservation_identity, restaurant_now)
        return await self._data_manager_reservations.cancel_reservation(current_reservation.confirmation_code, self._clock.now_utc())

    async def _load_booking_context(self) -> _BookingContext:
        restaurant_profile: RestaurantProfile = await self._data_manager_restaurant.get_restaurant_profile()
        reservation_policy: ReservationPolicy = restaurant_profile.reservation_policy
        restaurant_now: datetime = self._to_restaurant_now(restaurant_profile.time_zone)
        return _BookingContext(
            reservation_policy=reservation_policy,
            booking_window=SeatingRules.get_booking_window(
                restaurant_now, reservation_policy.minimum_lead_time_minutes, reservation_policy.booking_window_days
            ),
            seating_rhythm=SeatingRhythm(
                slot_interval_minutes=reservation_policy.slot_interval_minutes, seating_duration_minutes=reservation_policy.seating_duration_minutes
            ),
        )

    async def _get_restaurant_now(self) -> datetime:
        restaurant_profile: RestaurantProfile = await self._data_manager_restaurant.get_restaurant_profile()
        return self._to_restaurant_now(restaurant_profile.time_zone)

    async def _retrieve_changeable_reservation(self, reservation_identity: ReservationIdentity, restaurant_now: datetime) -> Reservation:
        current_reservation: Reservation = await self._data_manager_reservations.retrieve_booked_reservation(reservation_identity)
        if SeatingRules.has_started(current_reservation.reservation_date, current_reservation.starts_at, restaurant_now):
            raise ReservationAlreadyStartedException(
                current_reservation.confirmation_code, {"Reservation.ConfirmationCode": current_reservation.confirmation_code}
            )
        return current_reservation

    async def _plan_seating(self, requested_seating: RequestedSeating, booking_context: _BookingContext) -> _SeatingPlan:
        seating_window: SeatingWindow = await self._get_seating_window_or_refuse(
            requested_seating, booking_context.seating_rhythm.seating_duration_minutes
        )
        dining_tables: list[DiningTable] = await self._data_manager_restaurant.get_dining_tables()
        return _SeatingPlan(
            requested_seating=requested_seating,
            ends_at=SeatingRules.get_ends_at(requested_seating.starts_at, booking_context.seating_rhythm.seating_duration_minutes),
            seating_window=seating_window,
            fitting_tables=SeatingRules.get_fitting_tables(dining_tables, requested_seating.party_size),
            seating_rhythm=booking_context.seating_rhythm,
            earliest_start=booking_context.booking_window.earliest_start,
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

    async def _create_no_table_exception(self, seating_plan: _SeatingPlan, excluded_confirmation_code: str | None) -> NoTableAvailableException:
        # A booking being changed never blocks its own alternatives.
        seatings: list[Seating] = [
            seating
            for seating in await self._data_manager_reservations.find_seatings_on(seating_plan.requested_seating.reservation_date)
            if seating.confirmation_code != excluded_confirmation_code
        ]
        return NoTableAvailableException(
            requested_date=seating_plan.requested_seating.reservation_date,
            requested_time=seating_plan.requested_seating.starts_at,
            party_size=seating_plan.requested_seating.party_size,
            alternative_times=self._find_alternative_times(seating_plan, seatings),
            contextual_data_by_name={
                self.RESERVATION_DATE_CONTEXT_KEY: seating_plan.requested_seating.reservation_date.isoformat(),
                "Reservation.PartySize": seating_plan.requested_seating.party_size,
            },
        )

    @staticmethod
    def _find_alternative_times(seating_plan: _SeatingPlan, seatings: list[Seating]) -> list[time]:
        seating_day: SeatingDay = SeatingDay(
            reservation_date=seating_plan.requested_seating.reservation_date,
            seating_window=seating_plan.seating_window,
            fitting_tables=seating_plan.fitting_tables,
            seatings=seatings,
        )
        return SeatingRules.get_alternative_times(
            seating_day, seating_plan.requested_seating.starts_at, seating_plan.seating_rhythm, seating_plan.earliest_start
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
    def _to_current_seating(current_reservation: Reservation) -> RequestedSeating:
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
            current_booked_schedule=BookedSchedule(
                party_size=current_reservation.party_size,
                reservation_date=current_reservation.reservation_date,
                starts_at=current_reservation.starts_at,
                ends_at=current_reservation.ends_at,
                table_id=current_reservation.table_id,
                notes=current_reservation.notes,
            ),
            party_size=changed_requested_seating.party_size,
            reservation_date=changed_requested_seating.reservation_date,
            starts_at=changed_requested_seating.starts_at,
            ends_at=ends_at,
            notes=current_reservation.notes if validated_reservation_change.notes is None else validated_reservation_change.notes,
        )

    def _to_restaurant_now(self, time_zone: str) -> datetime:
        return self._clock.now_utc().astimezone(ZoneInfo(time_zone))
