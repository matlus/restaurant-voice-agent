from datetime import date, datetime, time, timedelta
from typing import Final

from voice_agent_restaurant.managers.exceptions.reservation_exceptions import (
    ReservationPolicyRefusedException,
    ReservationRequestValidationException,
)
from voice_agent_restaurant.managers.models.reservation_models import (
    CONFIRMATION_CODE_LENGTH,
    AvailabilityRequest,
    BookingWindow,
    RequestedSeating,
    ReservationCancellationRequest,
    ReservationChangeRequest,
    ReservationIdentity,
    ReservationRequest,
    ReservationSearchRequest,
    SeatingChange,
    ValidatedReservationChange,
    ValidatedReservationRequest,
)
from voice_agent_restaurant.managers.models.restaurant_models import ReservationPolicy
from voice_agent_restaurant.managers.validators.value_parsing.reservation_value_parsing import ReservationValueParsing


class ValidatorReservationRequests:
    """Front-door validation for every reservation request. Each stage reports all of its problems together.

    Values arrive as a voice model transcribed them. Each is trimmed and put into its stored form first (phone
    numbers to digits, confirmation codes to upper case) and then judged; a valid request comes back as typed
    values. Each request is judged in two stages. First it is read on its own, before anything is read from the store;
    a request that cannot be read raises ReservationRequestValidationException. Then a readable seating is judged
    against the restaurant's booking policy and booking window, by validate_requested_seating for a new seating or
    validate_changed_seating for a change; a seating the policy does not allow raises ReservationPolicyRefusedException.
    Whether the restaurant is open and whether a table is free are decided later, by the manager.
    """

    MAXIMUM_GUEST_NAME_LENGTH: Final[int] = 100
    MAXIMUM_NOTES_LENGTH: Final[int] = 300

    @classmethod
    def validate_availability_request(cls, availability_request: AvailabilityRequest) -> RequestedSeating:
        reservation_date_text: str | None = ReservationValueParsing.as_provided(availability_request.reservation_date)
        reservation_time_text: str | None = ReservationValueParsing.as_provided(availability_request.reservation_time)
        validation_problems: list[str] = cls._collect_required_seating_problems(
            reservation_date_text, reservation_time_text, availability_request.party_size
        )
        requested_seating: RequestedSeating | None = cls._to_requested_seating(
            reservation_date_text, reservation_time_text, availability_request.party_size
        )
        if requested_seating is None or validation_problems:
            raise cls._create_validation_exception(validation_problems)
        return requested_seating

    @classmethod
    def validate_reservation_request(cls, reservation_request: ReservationRequest) -> ValidatedReservationRequest:
        guest_name: str | None = ReservationValueParsing.as_provided(reservation_request.guest_name)
        phone_number: str | None = cls._as_phone_number(reservation_request.phone_number)
        reservation_date_text: str | None = ReservationValueParsing.as_provided(reservation_request.reservation_date)
        reservation_time_text: str | None = ReservationValueParsing.as_provided(reservation_request.reservation_time)
        notes: str | None = ReservationValueParsing.as_provided(reservation_request.notes)
        validation_problems: list[str] = []
        validation_problems.extend(cls._collect_guest_name_problems(guest_name))
        validation_problems.extend(cls._collect_phone_number_problems(phone_number))
        validation_problems.extend(
            cls._collect_required_seating_problems(reservation_date_text, reservation_time_text, reservation_request.party_size)
        )
        validation_problems.extend(cls._collect_notes_problems(notes))
        requested_seating: RequestedSeating | None = cls._to_requested_seating(
            reservation_date_text, reservation_time_text, reservation_request.party_size
        )
        if guest_name is None or phone_number is None or requested_seating is None or validation_problems:
            raise cls._create_validation_exception(validation_problems)
        return ValidatedReservationRequest(guest_name=guest_name, phone_number=phone_number, notes=notes, requested_seating=requested_seating)

    @classmethod
    def validate_search_request(cls, reservation_search_request: ReservationSearchRequest) -> str:
        """Returns the phone number to search by, reduced to its digits."""
        phone_number: str | None = cls._as_phone_number(reservation_search_request.phone_number)
        validation_problems: list[str] = cls._collect_phone_number_problems(phone_number)
        if phone_number is None or validation_problems:
            raise cls._create_validation_exception(validation_problems)
        return phone_number

    @classmethod
    def validate_cancellation_request(cls, reservation_cancellation_request: ReservationCancellationRequest) -> ReservationIdentity:
        confirmation_code: str | None = cls._as_confirmation_code(reservation_cancellation_request.confirmation_code)
        phone_number: str | None = cls._as_phone_number(reservation_cancellation_request.phone_number)
        validation_problems: list[str] = []
        validation_problems.extend(cls._collect_confirmation_code_problems(confirmation_code))
        validation_problems.extend(cls._collect_optional_phone_number_problems(phone_number))
        if confirmation_code is None or validation_problems:
            raise cls._create_validation_exception(validation_problems)
        return ReservationIdentity(confirmation_code=confirmation_code, phone_number=phone_number)

    @classmethod
    def validate_change_request(cls, reservation_change_request: ReservationChangeRequest) -> ValidatedReservationChange:
        """Judges the change request on its own. The changed seating is judged by validate_changed_seating once the
        current booking supplies the values left unchanged."""
        confirmation_code: str | None = cls._as_confirmation_code(reservation_change_request.confirmation_code)
        phone_number: str | None = cls._as_phone_number(reservation_change_request.phone_number)
        reservation_date_text: str | None = ReservationValueParsing.as_provided(reservation_change_request.reservation_date)
        reservation_time_text: str | None = ReservationValueParsing.as_provided(reservation_change_request.reservation_time)
        notes: str | None = ReservationValueParsing.as_provided(reservation_change_request.notes)
        validation_problems: list[str] = []
        validation_problems.extend(cls._collect_confirmation_code_problems(confirmation_code))
        validation_problems.extend(cls._collect_optional_phone_number_problems(phone_number))
        validation_problems.extend(
            cls._collect_requested_change_problems(reservation_date_text, reservation_time_text, reservation_change_request.party_size, notes)
        )
        validation_problems.extend(cls._collect_optional_date_problems(reservation_date_text))
        validation_problems.extend(cls._collect_optional_time_problems(reservation_time_text))
        validation_problems.extend(cls._collect_notes_problems(notes))
        if confirmation_code is None or validation_problems:
            raise cls._create_validation_exception(validation_problems)
        return ValidatedReservationChange(
            reservation_identity=ReservationIdentity(confirmation_code=confirmation_code, phone_number=phone_number),
            seating_change=SeatingChange(
                reservation_date=None if reservation_date_text is None else ReservationValueParsing.parse_date(reservation_date_text),
                starts_at=None if reservation_time_text is None else ReservationValueParsing.parse_time(reservation_time_text),
                party_size=reservation_change_request.party_size,
            ),
            notes=notes,
        )

    @classmethod
    def validate_requested_seating(
        cls, requested_seating: RequestedSeating, reservation_policy: ReservationPolicy, booking_window: BookingWindow
    ) -> None:
        """Judges a seating that is already well formed against the restaurant's booking policy and booking window."""
        policy_problems: list[str] = []
        policy_problems.extend(cls._collect_slot_boundary_problems(requested_seating.starts_at, reservation_policy.slot_interval_minutes))
        policy_problems.extend(cls._collect_party_size_problems(requested_seating.party_size, reservation_policy))
        policy_problems.extend(cls._collect_booking_window_problems(requested_seating.reservation_date, requested_seating.starts_at, booking_window))
        if policy_problems:
            raise cls._create_policy_refusal_exception(policy_problems)

    @classmethod
    def validate_changed_seating(
        cls,
        current_seating: RequestedSeating,
        changed_seating: RequestedSeating,
        reservation_policy: ReservationPolicy,
        booking_window: BookingWindow,
    ) -> None:
        """Judges only what a change moves. A new date or time must be bookable now and a new party size must be allowed;
        a booking left at its time and size keeps what it was booked under."""
        policy_problems: list[str] = []
        if (changed_seating.reservation_date, changed_seating.starts_at) != (current_seating.reservation_date, current_seating.starts_at):
            policy_problems.extend(cls._collect_slot_boundary_problems(changed_seating.starts_at, reservation_policy.slot_interval_minutes))
            policy_problems.extend(cls._collect_booking_window_problems(changed_seating.reservation_date, changed_seating.starts_at, booking_window))
        if changed_seating.party_size != current_seating.party_size:
            policy_problems.extend(cls._collect_party_size_problems(changed_seating.party_size, reservation_policy))
        if policy_problems:
            raise cls._create_policy_refusal_exception(policy_problems)

    @classmethod
    def _collect_required_seating_problems(
        cls, reservation_date_text: str | None, reservation_time_text: str | None, party_size: int | None
    ) -> list[str]:
        validation_problems: list[str] = []
        validation_problems.extend(cls._collect_required_date_problems(reservation_date_text))
        validation_problems.extend(cls._collect_required_time_problems(reservation_time_text))
        validation_problems.extend(cls._collect_required_party_size_problems(party_size))
        return validation_problems

    @staticmethod
    def _to_requested_seating(
        reservation_date_text: str | None, reservation_time_text: str | None, party_size: int | None
    ) -> RequestedSeating | None:
        reservation_date: date | None = None if reservation_date_text is None else ReservationValueParsing.parse_date(reservation_date_text)
        starts_at: time | None = None if reservation_time_text is None else ReservationValueParsing.parse_time(reservation_time_text)
        if reservation_date is None or starts_at is None or party_size is None:
            return None
        return RequestedSeating(reservation_date=reservation_date, starts_at=starts_at, party_size=party_size)

    @classmethod
    def _collect_required_date_problems(cls, reservation_date_text: str | None) -> list[str]:
        if reservation_date_text is None:
            return ["'reservation_date' is required but was not provided"]
        return cls._collect_optional_date_problems(reservation_date_text)

    @staticmethod
    def _collect_optional_date_problems(reservation_date_text: str | None) -> list[str]:
        if reservation_date_text is not None and ReservationValueParsing.parse_date(reservation_date_text) is None:
            return [f"'reservation_date' value '{reservation_date_text}' is not a date in the form YYYY-MM-DD"]
        return []

    @classmethod
    def _collect_required_time_problems(cls, reservation_time_text: str | None) -> list[str]:
        if reservation_time_text is None:
            return ["'reservation_time' is required but was not provided"]
        return cls._collect_optional_time_problems(reservation_time_text)

    @staticmethod
    def _collect_optional_time_problems(reservation_time_text: str | None) -> list[str]:
        if reservation_time_text is not None and ReservationValueParsing.parse_time(reservation_time_text) is None:
            return [f"'reservation_time' value '{reservation_time_text}' is not a time such as 18:30 or 6:30 PM"]
        return []

    @staticmethod
    def _collect_slot_boundary_problems(starts_at: time, slot_interval_minutes: int) -> list[str]:
        # The seed reader refuses an interval that does not divide an hour and an opening time off the grid, so the
        # minute of the hour alone decides whether a time is on the grid SeatingRules steps from each opening time.
        minutes_past_slot: int = starts_at.minute % slot_interval_minutes
        if minutes_past_slot == 0:
            return []
        earlier_slot: datetime = datetime.combine(date.min, starts_at.replace(second=0, microsecond=0)) - timedelta(minutes=minutes_past_slot)
        later_slot: datetime = earlier_slot + timedelta(minutes=slot_interval_minutes)
        return [
            (
                f"tables are booked every {slot_interval_minutes} minutes, so {starts_at:%H:%M} cannot be booked; "
                f"the nearest times are {earlier_slot:%H:%M} and {later_slot:%H:%M}"
            )
        ]

    @staticmethod
    def _collect_required_party_size_problems(party_size: int | None) -> list[str]:
        if party_size is None:
            return ["'party_size' is required but was not provided"]
        return []

    @staticmethod
    def _collect_party_size_problems(party_size: int, reservation_policy: ReservationPolicy) -> list[str]:
        if party_size < reservation_policy.minimum_party_size:
            return [f"'party_size' must be at least {reservation_policy.minimum_party_size} but was {party_size}"]
        if party_size > reservation_policy.maximum_party_size:
            return [
                (
                    f"'party_size' of {party_size} is larger than the {reservation_policy.maximum_party_size} guests that can be booked by phone. "
                    f"{reservation_policy.large_party_guidance}"
                )
            ]
        return []

    @classmethod
    def _collect_booking_window_problems(cls, reservation_date: date, starts_at: time, booking_window: BookingWindow) -> list[str]:
        restaurant_now: datetime = booking_window.restaurant_now
        requested_start: datetime = datetime.combine(reservation_date, starts_at, tzinfo=restaurant_now.tzinfo)
        if requested_start < restaurant_now:
            return [f"{reservation_date.isoformat()} at {starts_at:%H:%M} has already passed; it is now {restaurant_now:%Y-%m-%d %H:%M}"]
        if reservation_date > booking_window.last_date:
            booking_window_days: int = (booking_window.last_date - restaurant_now.date()).days
            return [
                (
                    f"{reservation_date.isoformat()} is more than {booking_window_days} days ahead; "
                    f"bookings open up to {booking_window.last_date.isoformat()}"
                )
            ]
        return []

    @staticmethod
    def _collect_requested_change_problems(
        reservation_date_text: str | None, reservation_time_text: str | None, party_size: int | None, notes: str | None
    ) -> list[str]:
        if reservation_date_text is None and reservation_time_text is None and party_size is None and notes is None:
            return ["at least one of 'reservation_date', 'reservation_time', 'party_size' or 'notes' must be provided to change"]
        return []

    @classmethod
    def _collect_guest_name_problems(cls, guest_name: str | None) -> list[str]:
        if guest_name is None:
            return ["'guest_name' is required but was not provided"]
        if len(guest_name) > cls.MAXIMUM_GUEST_NAME_LENGTH:
            return [f"'guest_name' must contain at most {cls.MAXIMUM_GUEST_NAME_LENGTH} characters"]
        return []

    @classmethod
    def _collect_optional_phone_number_problems(cls, phone_number: str | None) -> list[str]:
        return [] if phone_number is None else cls._collect_phone_number_problems(phone_number)

    @staticmethod
    def _collect_phone_number_problems(phone_number: str | None) -> list[str]:
        if phone_number is None:
            return ["'phone_number' is required but was not provided"]
        if not ReservationValueParsing.is_phone_number(phone_number):
            return [f"'phone_number' value '{phone_number}' must be a 10-digit phone number"]
        return []

    @staticmethod
    def _collect_confirmation_code_problems(confirmation_code: str | None) -> list[str]:
        if confirmation_code is None:
            return ["'confirmation_code' is required but was not provided"]
        if not ReservationValueParsing.is_confirmation_code(confirmation_code):
            return [f"'confirmation_code' value '{confirmation_code}' is not a {CONFIRMATION_CODE_LENGTH}-character confirmation code"]
        return []

    @classmethod
    def _collect_notes_problems(cls, notes: str | None) -> list[str]:
        if notes is not None and len(notes) > cls.MAXIMUM_NOTES_LENGTH:
            return [f"'notes' must contain at most {cls.MAXIMUM_NOTES_LENGTH} characters"]
        return []

    @staticmethod
    def _as_phone_number(phone_number: str | None) -> str | None:
        provided_phone_number: str | None = ReservationValueParsing.as_provided(phone_number)
        return None if provided_phone_number is None else ReservationValueParsing.normalize_phone_number(provided_phone_number)

    @staticmethod
    def _as_confirmation_code(confirmation_code: str | None) -> str | None:
        provided_confirmation_code: str | None = ReservationValueParsing.as_provided(confirmation_code)
        return None if provided_confirmation_code is None else ReservationValueParsing.normalize_confirmation_code(provided_confirmation_code)

    @staticmethod
    def _create_validation_exception(validation_problems: list[str]) -> ReservationRequestValidationException:
        return ReservationRequestValidationException(validation_problems, {"Reservation.ProblemCount": len(validation_problems)})

    @staticmethod
    def _create_policy_refusal_exception(policy_problems: list[str]) -> ReservationPolicyRefusedException:
        return ReservationPolicyRefusedException(policy_problems, {"Reservation.ProblemCount": len(policy_problems)})
