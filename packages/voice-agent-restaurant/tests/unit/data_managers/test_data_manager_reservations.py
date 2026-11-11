# Class tests for the store's guard against a lost update. A DomainFacade change reads the booking and rewrites it on
# separate connections, and no facade scenario can place another writer between the two. These tests do: they decide a
# change from a booking they read through the facade, let the facade change or cancel that booking first, and only then
# ask the store to apply the change decided from the stale read.

from datetime import datetime
from pathlib import Path
from typing import Final

import pytest

from acceptance_support.asserters.asserter_exception import AsserterException, ExpectedExceptionMetadata
from acceptance_support.generated_guests import create_generated_note
from acceptance_support.service_locator_testing import WEDNESDAY_AFTERNOON_UTC, ClockFixed, create_domain_facade
from voice_agent_restaurant import (
    DomainFacade,
    ExceptionAction,
    LogEventReservation,
    Reservation,
    ReservationCancellationRequest,
    ReservationChangedConcurrentlyException,
    ReservationChangeRequest,
    ReservationNotFoundException,
    ReservationSearchRequest,
    Severity,
)
from voice_agent_restaurant.managers.data_managers.data_manager_reservations import DataManagerReservations
from voice_agent_restaurant.managers.models.reservation_models import BookedSchedule, ReservationReschedule

SEEDED_PRIYA_PHONE: Final[str] = "5550101001"


async def read_unstarted_seeded_booking(domain_facade: DomainFacade, phone_number: str) -> Reservation:
    """The seeded booking for the phone number, guarded to start after the restaurant's local now, because the facade
    change or cancel each test makes first refuses a booking that has started."""
    found_reservations: list[Reservation] = await domain_facade.find_reservations(ReservationSearchRequest(phone_number=phone_number))
    assert len(found_reservations) == 1, f"The seed must hold exactly one upcoming booking for {phone_number}; found {found_reservations!r}"
    seeded_reservation: Reservation = found_reservations[0]
    restaurant_local_now: datetime = await domain_facade.get_restaurant_local_now()
    seeded_start: datetime = datetime.combine(seeded_reservation.reservation_date, seeded_reservation.starts_at, tzinfo=restaurant_local_now.tzinfo)
    assert seeded_start > restaurant_local_now, (
        f"The lost-update scenarios need booking {seeded_reservation.confirmation_code} to start after {restaurant_local_now}, but it "
        f"starts at {seeded_start}; the seeded data no longer supports these scenarios"
    )
    return seeded_reservation


def create_notes_reschedule(read_reservation: Reservation, requested_notes: str) -> ReservationReschedule:
    return ReservationReschedule(
        confirmation_code=read_reservation.confirmation_code,
        current_booked_schedule=BookedSchedule(
            party_size=read_reservation.party_size,
            reservation_date=read_reservation.reservation_date,
            starts_at=read_reservation.starts_at,
            ends_at=read_reservation.ends_at,
            table_id=read_reservation.table_id,
            notes=read_reservation.notes,
        ),
        party_size=read_reservation.party_size,
        reservation_date=read_reservation.reservation_date,
        starts_at=read_reservation.starts_at,
        ends_at=read_reservation.ends_at,
        notes=requested_notes,
    )


class TestDataManagerReservationsReschedule:
    async def test_RescheduleReservation_WhenTheBookingChangedAfterItWasRead_ThenTheChangeIsRefusedAndTheOtherChangeKept(
        self, restaurant_database_path: Path
    ) -> None:
        data_manager_reservations: DataManagerReservations = DataManagerReservations(restaurant_database_path, ClockFixed(WEDNESDAY_AFTERNOON_UTC))
        expected_exception_metadata: ExpectedExceptionMetadata = ExpectedExceptionMetadata(
            http_status_code=409,
            exception_action=ExceptionAction.USER_ACTION_REQUIRED,
            reason="The reservation was changed by another request",
            severity=Severity.ERROR,
            log_event=LogEventReservation.RESERVATION_SCHEDULING,
        )

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            read_reservation: Reservation = await read_unstarted_seeded_booking(domain_facade, SEEDED_PRIYA_PHONE)
            stale_reservation_reschedule: ReservationReschedule = create_notes_reschedule(read_reservation, create_generated_note())
            expected_message_phrases: list[str] = [read_reservation.confirmation_code, "was changed by another request", "nothing was changed"]
            expected_contextual_data_by_name: dict[str, str] = {"Reservation.ConfirmationCode": read_reservation.confirmation_code}
            expected_reservations: list[Reservation] = [
                await domain_facade.change_reservation(
                    ReservationChangeRequest(
                        confirmation_code=read_reservation.confirmation_code,
                        phone_number=SEEDED_PRIYA_PHONE,
                        reservation_date=None,
                        reservation_time=None,
                        party_size=None,
                        notes=create_generated_note(),
                    )
                )
            ]
            with pytest.raises(ReservationChangedConcurrentlyException) as raised:
                await data_manager_reservations.reschedule_reservation(
                    stale_reservation_reschedule, [read_reservation.table_id], WEDNESDAY_AFTERNOON_UTC
                )
            actual_found_reservations: list[Reservation] = await domain_facade.find_reservations(
                ReservationSearchRequest(phone_number=SEEDED_PRIYA_PHONE)
            )

        AsserterException.assert_message_and_metadata_are_as_expected(
            expected_message_phrases=expected_message_phrases,
            expected_exception_metadata=expected_exception_metadata,
            expected_contextual_data_by_name=expected_contextual_data_by_name,
            actual_voice_agent_restaurant_exception=raised.value,
        )
        assert actual_found_reservations == expected_reservations

    async def test_RescheduleReservation_WhenTheBookingWasCancelledAfterItWasRead_ThenItIsNotFound(self, restaurant_database_path: Path) -> None:
        data_manager_reservations: DataManagerReservations = DataManagerReservations(restaurant_database_path, ClockFixed(WEDNESDAY_AFTERNOON_UTC))
        expected_found_reservations: list[Reservation] = []
        expected_exception_metadata: ExpectedExceptionMetadata = ExpectedExceptionMetadata(
            http_status_code=404,
            exception_action=ExceptionAction.USER_ACTION_REQUIRED,
            reason="The reservation was not found",
            severity=Severity.ERROR,
            log_event=LogEventReservation.RESERVATION_LOOKUP,
        )

        async with create_domain_facade(restaurant_database_path) as domain_facade:
            read_reservation: Reservation = await read_unstarted_seeded_booking(domain_facade, SEEDED_PRIYA_PHONE)
            stale_reservation_reschedule: ReservationReschedule = create_notes_reschedule(read_reservation, create_generated_note())
            expected_message_phrases: list[str] = [read_reservation.confirmation_code, "No current reservation matches confirmation code"]
            expected_contextual_data_by_name: dict[str, str] = {"Reservation.ConfirmationCode": read_reservation.confirmation_code}
            await domain_facade.cancel_reservation(
                ReservationCancellationRequest(confirmation_code=read_reservation.confirmation_code, phone_number=SEEDED_PRIYA_PHONE)
            )
            with pytest.raises(ReservationNotFoundException) as raised:
                await data_manager_reservations.reschedule_reservation(
                    stale_reservation_reschedule, [read_reservation.table_id], WEDNESDAY_AFTERNOON_UTC
                )
            actual_found_reservations: list[Reservation] = await domain_facade.find_reservations(
                ReservationSearchRequest(phone_number=SEEDED_PRIYA_PHONE)
            )

        AsserterException.assert_message_and_metadata_are_as_expected(
            expected_message_phrases=expected_message_phrases,
            expected_exception_metadata=expected_exception_metadata,
            expected_contextual_data_by_name=expected_contextual_data_by_name,
            actual_voice_agent_restaurant_exception=raised.value,
        )
        assert actual_found_reservations == expected_found_reservations
