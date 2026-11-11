from datetime import date, time
from typing import final, override

from voice_agent_restaurant.managers.exceptions.voice_agent_restaurant_exceptions import (
    ContextualDataDict,
    LogEventBase,
    VoiceAgentRestaurantBusinessBaseException,
)


class LogEventReservation(LogEventBase):
    RESERVATION_REQUEST_VALIDATION_FAILED = "ReservationRequestValidationFailed"
    RESERVATION_POLICY_REFUSED = "ReservationPolicyRefused"
    RESERVATION_SCHEDULING = "ReservationScheduling"
    RESERVATION_LOOKUP = "ReservationLookup"


def _format_time(time_of_day: time) -> str:
    return time_of_day.strftime("%H:%M")


@final
class ReservationRequestValidationException(VoiceAgentRestaurantBusinessBaseException):
    """The reservation request could not be read: every missing or malformed value, reported together.

    The sender must correct the request itself; a request that reads well but is not allowed raises
    ReservationPolicyRefusedException instead.
    """

    def __init__(self, validation_problems: list[str], contextual_data_by_name: ContextualDataDict | None = None) -> None:
        super().__init__(
            message=f"Reservation request is invalid: {'; '.join(validation_problems)}",
            log_event=LogEventReservation.RESERVATION_REQUEST_VALIDATION_FAILED,
            contextual_data_by_name=contextual_data_by_name,
        )
        self.validation_problems: list[str] = validation_problems

    @property
    @override
    def reason(self) -> str:
        return "Reservation request failed validation"


@final
class ReservationPolicyRefusedException(VoiceAgentRestaurantBusinessBaseException):
    """A well-formed reservation request that the booking policy or booking window does not allow, such as a party too
    large to book by phone or a time that has passed. Every reason is reported together, written to be told to the guest."""

    def __init__(self, policy_problems: list[str], contextual_data_by_name: ContextualDataDict | None = None) -> None:
        super().__init__(
            message=f"The restaurant cannot take this reservation: {'; '.join(policy_problems)}",
            log_event=LogEventReservation.RESERVATION_POLICY_REFUSED,
            contextual_data_by_name=contextual_data_by_name,
        )
        self.policy_problems: list[str] = policy_problems

    @property
    @override
    def reason(self) -> str:
        return "Reservation request is not allowed by the booking policy"


@final
class RestaurantClosedOnDateException(VoiceAgentRestaurantBusinessBaseException):
    def __init__(self, requested_date: date, closure_reason: str, contextual_data_by_name: ContextualDataDict | None = None) -> None:
        super().__init__(
            message=f"The restaurant is closed on {requested_date:%A} {requested_date.isoformat()} ({closure_reason}).",
            log_event=LogEventReservation.RESERVATION_SCHEDULING,
            contextual_data_by_name=contextual_data_by_name,
        )
        self.requested_date: date = requested_date
        self.closure_reason: str = closure_reason

    @property
    @override
    def reason(self) -> str:
        return "The restaurant is closed on the requested date"


@final
class OutsideSeatingHoursException(VoiceAgentRestaurantBusinessBaseException):
    """The time is not one at which a table can be seated: before opening, or too close to closing for a full seating."""

    def __init__(
        self,
        requested_date: date,
        requested_time: time,
        first_seating_time: time,
        last_seating_time: time,
        contextual_data_by_name: ContextualDataDict | None = None,
    ) -> None:
        super().__init__(
            message=(
                f"{_format_time(requested_time)} is outside seating hours on {requested_date.isoformat()}. "
                f"Tables can be booked from {_format_time(first_seating_time)} to {_format_time(last_seating_time)} that day."
            ),
            log_event=LogEventReservation.RESERVATION_SCHEDULING,
            contextual_data_by_name=contextual_data_by_name,
        )
        self.first_seating_time: time = first_seating_time
        self.last_seating_time: time = last_seating_time

    @property
    @override
    def reason(self) -> str:
        return "The requested time is outside seating hours"


@final
class NoTableAvailableException(VoiceAgentRestaurantBusinessBaseException):
    """Every table that fits the party is taken at the requested time. Nearby open times are named when there are any."""

    def __init__(
        self,
        requested_date: date,
        requested_time: time,
        party_size: int,
        alternative_times: list[time],
        contextual_data_by_name: ContextualDataDict | None = None,
    ) -> None:
        alternatives_sentence: str = (
            f" Open times that day: {', '.join(_format_time(alternative_time) for alternative_time in alternative_times)}."
            if alternative_times
            else " There are no other open times for this party size that day."
        )
        super().__init__(
            message=(
                f"No table for {party_size} is available at {_format_time(requested_time)} on {requested_date.isoformat()}.{alternatives_sentence}"
            ),
            log_event=LogEventReservation.RESERVATION_SCHEDULING,
            contextual_data_by_name=contextual_data_by_name,
        )
        self.alternative_times: list[time] = alternative_times

    @property
    @override
    def reason(self) -> str:
        return "No table is available at the requested time"

    @property
    @override
    def http_status_code(self) -> int:
        return 409


# The messages below are read to the caller, who may have identified the booking without its confirmation code, so they
# never repeat the code; it is kept in the contextual data for the logs.


@final
class ReservationNotFoundException(VoiceAgentRestaurantBusinessBaseException):
    """No booked reservation matches the confirmation code, or the phone number given with it. Which was wrong is never revealed."""

    def __init__(self, confirmation_code: str, contextual_data_by_name: ContextualDataDict | None = None) -> None:
        super().__init__(
            message=(
                "No current booking matches that confirmation code. Check the code, or find the booking by the phone number, name and "
                "date it is booked under."
            ),
            log_event=LogEventReservation.RESERVATION_LOOKUP,
            contextual_data_by_name=contextual_data_by_name,
        )
        self.confirmation_code: str = confirmation_code

    @property
    @override
    def reason(self) -> str:
        return "The reservation was not found"

    @property
    @override
    def http_status_code(self) -> int:
        return 404


@final
class GuestReservationNotFoundException(VoiceAgentRestaurantBusinessBaseException):
    """No single upcoming booking at this date and time matches the phone number and name given. Which detail was wrong is
    never revealed, so the refusal cannot be used to learn whose bookings exist."""

    def __init__(self, reservation_date: date, starts_at: time, contextual_data_by_name: ContextualDataDict | None = None) -> None:
        super().__init__(
            message=(
                f"No current booking at {_format_time(starts_at)} on {reservation_date.isoformat()} matches that phone number and name. "
                "Check the details, or use the booking's confirmation code."
            ),
            log_event=LogEventReservation.RESERVATION_LOOKUP,
            contextual_data_by_name=contextual_data_by_name,
        )
        self.reservation_date: date = reservation_date
        self.starts_at: time = starts_at

    @property
    @override
    def reason(self) -> str:
        return "The reservation was not found"

    @property
    @override
    def http_status_code(self) -> int:
        return 404


@final
class ReservationAlreadyStartedException(VoiceAgentRestaurantBusinessBaseException):
    def __init__(self, confirmation_code: str, contextual_data_by_name: ContextualDataDict | None = None) -> None:
        super().__init__(
            message="That booking has already started, so it can no longer be changed or cancelled by phone.",
            log_event=LogEventReservation.RESERVATION_SCHEDULING,
            contextual_data_by_name=contextual_data_by_name,
        )
        self.confirmation_code: str = confirmation_code

    @property
    @override
    def reason(self) -> str:
        return "The reservation has already started"

    @property
    @override
    def http_status_code(self) -> int:
        return 409


@final
class ReservationChangedConcurrentlyException(VoiceAgentRestaurantBusinessBaseException):
    """The booking changed after this change was decided from it, so applying the change would overwrite the other one.
    Nothing was written."""

    def __init__(self, confirmation_code: str, contextual_data_by_name: ContextualDataDict | None = None) -> None:
        super().__init__(
            message=(
                "That booking was changed by another request while this change was being made, so nothing was changed. "
                "Look the booking up again and repeat the change."
            ),
            log_event=LogEventReservation.RESERVATION_SCHEDULING,
            contextual_data_by_name=contextual_data_by_name,
        )
        self.confirmation_code: str = confirmation_code

    @property
    @override
    def reason(self) -> str:
        return "The reservation was changed by another request"

    @property
    @override
    def http_status_code(self) -> int:
        return 409


@final
class CandidateTablesTakenException(VoiceAgentRestaurantBusinessBaseException):
    """Every candidate table was taken when the store came to seat the booking. Nothing was written.

    The reservations manager translates it into NoTableAvailableException, adding the nearby open times; it never
    leaves the package.
    """

    def __init__(self, reservation_date: date, starts_at: time, contextual_data_by_name: ContextualDataDict | None = None) -> None:
        super().__init__(
            message=f"Every candidate table is taken at {_format_time(starts_at)} on {reservation_date.isoformat()}.",
            log_event=LogEventReservation.RESERVATION_SCHEDULING,
            contextual_data_by_name=contextual_data_by_name,
        )

    @property
    @override
    def reason(self) -> str:
        return "Every candidate table is taken"

    @property
    @override
    def http_status_code(self) -> int:
        return 409
