import asyncio
import secrets
import sqlite3
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import Final

from voice_agent_restaurant.managers.clocks.clock_base import ClockBase
from voice_agent_restaurant.managers.data_managers.exception_translators.translator_restaurant_store_exceptions import (
    TranslatorRestaurantStoreExceptions,
)
from voice_agent_restaurant.managers.data_managers.store.restaurant_store_connector import RestaurantStoreConnector
from voice_agent_restaurant.managers.data_managers.store.store_value_conversion import from_minutes_after_midnight, to_minutes_after_midnight
from voice_agent_restaurant.managers.exceptions.reservation_exceptions import (
    CandidateTablesTakenException,
    ReservationChangedConcurrentlyException,
    ReservationNotFoundException,
)
from voice_agent_restaurant.managers.exceptions.restaurant_store_exceptions import RestaurantStoreContractViolationException
from voice_agent_restaurant.managers.models.reservation_models import (
    CONFIRMATION_CODE_ALPHABET,
    CONFIRMATION_CODE_LENGTH,
    BookedSchedule,
    NewReservation,
    Reservation,
    ReservationIdentity,
    ReservationReschedule,
    ReservationStatus,
    Seating,
)


@dataclass(frozen=True)
class _TableSlot:
    """The time a booking needs a table for. Its own current seating, named by confirmation_code, never blocks it."""

    reservation_date: date
    starts_at: time
    ends_at: time
    confirmation_code: str


class DataManagerReservations:
    """Owns all reservation reads and writes.

    Seating a booking is check-then-write, so it runs inside one IMMEDIATE transaction: no other
    writer can take the same table between the overlap check and the insert or update. The manager
    decides which tables are acceptable and in what order; this class only takes the first one free.
    Every write commits as its last statement, after the row it returns has been read back.
    """

    MAXIMUM_CONFIRMATION_CODE_ATTEMPTS: Final[int] = 10
    _CONFIRMATION_CODE_CONTEXT_KEY: Final[str] = "Reservation.ConfirmationCode"
    _RESERVATION_DATE_CONTEXT_KEY: Final[str] = "Reservation.Date"
    _RESERVATION_COLUMNS: Final[str] = (
        "confirmation_code, guest_name, phone_number, party_size, reservation_date, starts_at_minutes, ends_at_minutes, table_id, notes, status"
    )
    _OVERLAPPING_SEATING_QUERY: Final[str] = """
        SELECT 1 FROM reservations
        WHERE table_id = ? AND reservation_date = ? AND status = ? AND confirmation_code <> ?
          AND starts_at_minutes < ? AND ? < ends_at_minutes
        LIMIT 1
    """

    def __init__(self, database_path: Path, clock: ClockBase) -> None:
        self._restaurant_store_connector: RestaurantStoreConnector = RestaurantStoreConnector(database_path, clock)

    async def find_seatings_on(self, reservation_date: date) -> list[Seating]:
        return await asyncio.to_thread(self._find_seatings_on_synchronously, reservation_date)

    async def record_reservation(self, new_reservation: NewReservation, candidate_table_ids: Sequence[str], now_utc: datetime) -> Reservation:
        """Assigns a confirmation code, seats the booking at the first free candidate table and records it.

        Raises CandidateTablesTakenException, writing nothing, when every candidate is taken.
        """
        return await asyncio.to_thread(self._record_reservation_synchronously, new_reservation, candidate_table_ids, now_utc)

    async def retrieve_booked_reservation(self, reservation_identity: ReservationIdentity) -> Reservation:
        return await asyncio.to_thread(self._retrieve_booked_reservation_synchronously, reservation_identity)

    async def find_booked_reservations(self, phone_number: str, first_date: date) -> list[Reservation]:
        return await asyncio.to_thread(self._find_booked_reservations_synchronously, phone_number, first_date)

    async def reschedule_reservation(
        self, reservation_reschedule: ReservationReschedule, candidate_table_ids: Sequence[str], now_utc: datetime
    ) -> Reservation:
        """Moves a booked reservation to the first free candidate table at its new time.

        Raises CandidateTablesTakenException when every candidate is taken, ReservationNotFoundException when the
        booking is no longer booked, and ReservationChangedConcurrentlyException when it no longer holds the schedule
        the change was decided from. In every case nothing is written.
        """
        return await asyncio.to_thread(self._reschedule_reservation_synchronously, reservation_reschedule, candidate_table_ids, now_utc)

    async def cancel_reservation(self, confirmation_code: str, now_utc: datetime) -> Reservation:
        """Cancels a booked reservation. Raises ReservationNotFoundException, writing nothing, when it is no longer booked."""
        return await asyncio.to_thread(self._cancel_reservation_synchronously, confirmation_code, now_utc)

    def _find_seatings_on_synchronously(self, reservation_date: date) -> list[Seating]:
        try:
            with self._restaurant_store_connector.open_connection() as connection:
                seating_rows: list[sqlite3.Row] = connection.execute(
                    """
                    SELECT confirmation_code, table_id, starts_at_minutes, ends_at_minutes
                    FROM reservations WHERE reservation_date = ? AND status = ?
                    """,
                    (reservation_date.isoformat(), ReservationStatus.BOOKED.value),
                ).fetchall()
        except (sqlite3.Error, OSError) as store_error:
            raise TranslatorRestaurantStoreExceptions.translate(
                store_error, "read the seatings for a date", {self._RESERVATION_DATE_CONTEXT_KEY: reservation_date.isoformat()}
            ) from store_error
        return [self._map_seating_row(seating_row) for seating_row in seating_rows]

    def _record_reservation_synchronously(
        self, new_reservation: NewReservation, candidate_table_ids: Sequence[str], now_utc: datetime
    ) -> Reservation:
        try:
            with self._restaurant_store_connector.open_connection() as connection:
                reservation: Reservation = self._run_in_immediate_transaction(
                    connection, lambda: self._seat_new_reservation(connection, new_reservation, candidate_table_ids, now_utc)
                )
        except (sqlite3.Error, OSError) as store_error:
            raise TranslatorRestaurantStoreExceptions.translate(
                store_error, "record the reservation", {self._RESERVATION_DATE_CONTEXT_KEY: new_reservation.reservation_date.isoformat()}
            ) from store_error
        return reservation

    def _reschedule_reservation_synchronously(
        self, reservation_reschedule: ReservationReschedule, candidate_table_ids: Sequence[str], now_utc: datetime
    ) -> Reservation:
        try:
            with self._restaurant_store_connector.open_connection() as connection:
                reservation: Reservation = self._run_in_immediate_transaction(
                    connection, lambda: self._move_booked_reservation(connection, reservation_reschedule, candidate_table_ids, now_utc)
                )
        except (sqlite3.Error, OSError) as store_error:
            raise TranslatorRestaurantStoreExceptions.translate(
                store_error, "change the reservation", {self._CONFIRMATION_CODE_CONTEXT_KEY: reservation_reschedule.confirmation_code}
            ) from store_error
        return reservation

    def _cancel_reservation_synchronously(self, confirmation_code: str, now_utc: datetime) -> Reservation:
        try:
            with self._restaurant_store_connector.open_connection() as connection:
                reservation: Reservation = self._run_in_immediate_transaction(
                    connection, lambda: self._cancel_booked_reservation(connection, confirmation_code, now_utc)
                )
        except (sqlite3.Error, OSError) as store_error:
            raise TranslatorRestaurantStoreExceptions.translate(
                store_error, "cancel the reservation", {self._CONFIRMATION_CODE_CONTEXT_KEY: confirmation_code}
            ) from store_error
        return reservation

    def _retrieve_booked_reservation_synchronously(self, reservation_identity: ReservationIdentity) -> Reservation:
        try:
            with self._restaurant_store_connector.open_connection() as connection:
                reservation_row: sqlite3.Row | None = connection.execute(
                    f"SELECT {self._RESERVATION_COLUMNS} FROM reservations WHERE confirmation_code = ? AND phone_number = ? AND status = ?",  # noqa: S608 - constant column list
                    (reservation_identity.confirmation_code, reservation_identity.phone_number, ReservationStatus.BOOKED.value),
                ).fetchone()
        except (sqlite3.Error, OSError) as store_error:
            raise TranslatorRestaurantStoreExceptions.translate(
                store_error, "read the reservation", {self._CONFIRMATION_CODE_CONTEXT_KEY: reservation_identity.confirmation_code}
            ) from store_error
        if reservation_row is None:
            raise ReservationNotFoundException(
                reservation_identity.confirmation_code, {self._CONFIRMATION_CODE_CONTEXT_KEY: reservation_identity.confirmation_code}
            )
        return self._map_reservation_row(reservation_row)

    def _find_booked_reservations_synchronously(self, phone_number: str, first_date: date) -> list[Reservation]:
        try:
            with self._restaurant_store_connector.open_connection() as connection:
                reservation_rows: list[sqlite3.Row] = connection.execute(
                    f"""
                    SELECT {self._RESERVATION_COLUMNS} FROM reservations
                    WHERE phone_number = ? AND status = ? AND reservation_date >= ?
                    ORDER BY reservation_date, starts_at_minutes
                    """,  # noqa: S608 - constant column list
                    (phone_number, ReservationStatus.BOOKED.value, first_date.isoformat()),
                ).fetchall()
        except (sqlite3.Error, OSError) as store_error:
            # The phone number stays out of the diagnostic record; the date bound identifies the query well enough.
            raise TranslatorRestaurantStoreExceptions.translate(
                store_error, "look up reservations by phone number", {"Reservation.FirstDate": first_date.isoformat()}
            ) from store_error
        return [self._map_reservation_row(reservation_row) for reservation_row in reservation_rows]

    def _seat_new_reservation(
        self, connection: sqlite3.Connection, new_reservation: NewReservation, candidate_table_ids: Sequence[str], now_utc: datetime
    ) -> Reservation:
        confirmation_code: str = self._create_unused_confirmation_code(connection)
        table_slot: _TableSlot = _TableSlot(
            reservation_date=new_reservation.reservation_date,
            starts_at=new_reservation.starts_at,
            ends_at=new_reservation.ends_at,
            confirmation_code=confirmation_code,
        )
        free_table_id: str = self._retrieve_first_free_table_id(connection, table_slot, candidate_table_ids)
        self._insert_reservation(connection, new_reservation, confirmation_code, free_table_id, now_utc)
        return self._read_reservation(connection, confirmation_code)

    def _move_booked_reservation(
        self, connection: sqlite3.Connection, reservation_reschedule: ReservationReschedule, candidate_table_ids: Sequence[str], now_utc: datetime
    ) -> Reservation:
        table_slot: _TableSlot = _TableSlot(
            reservation_date=reservation_reschedule.reservation_date,
            starts_at=reservation_reschedule.starts_at,
            ends_at=reservation_reschedule.ends_at,
            confirmation_code=reservation_reschedule.confirmation_code,
        )
        free_table_id: str = self._retrieve_first_free_table_id(connection, table_slot, candidate_table_ids)
        self._update_reservation_schedule(connection, reservation_reschedule, free_table_id, now_utc)
        return self._read_reservation(connection, reservation_reschedule.confirmation_code)

    def _cancel_booked_reservation(self, connection: sqlite3.Connection, confirmation_code: str, now_utc: datetime) -> Reservation:
        cancel_cursor: sqlite3.Cursor = connection.execute(
            "UPDATE reservations SET status = ?, updated_at_utc = ? WHERE confirmation_code = ? AND status = ?",
            (ReservationStatus.CANCELLED.value, now_utc.isoformat(), confirmation_code, ReservationStatus.BOOKED.value),
        )
        if cancel_cursor.rowcount != 1:
            raise ReservationNotFoundException(confirmation_code, {self._CONFIRMATION_CODE_CONTEXT_KEY: confirmation_code})
        return self._read_reservation(connection, confirmation_code)

    def _create_unused_confirmation_code(self, connection: sqlite3.Connection) -> str:
        for _ in range(self.MAXIMUM_CONFIRMATION_CODE_ATTEMPTS):
            candidate_code: str = "".join(secrets.choice(CONFIRMATION_CODE_ALPHABET) for _ in range(CONFIRMATION_CODE_LENGTH))
            if connection.execute("SELECT 1 FROM reservations WHERE confirmation_code = ?", (candidate_code,)).fetchone() is None:
                return candidate_code
        raise RestaurantStoreContractViolationException(
            message=f"No unused confirmation code was found in {self.MAXIMUM_CONFIRMATION_CODE_ATTEMPTS} attempts",
            contextual_data_by_name={"Reservation.ConfirmationCodeAttempts": self.MAXIMUM_CONFIRMATION_CODE_ATTEMPTS},
        )

    def _retrieve_first_free_table_id(self, connection: sqlite3.Connection, table_slot: _TableSlot, candidate_table_ids: Iterable[str]) -> str:
        for candidate_table_id in candidate_table_ids:
            overlapping_row: sqlite3.Row | None = connection.execute(
                self._OVERLAPPING_SEATING_QUERY,
                (
                    candidate_table_id,
                    table_slot.reservation_date.isoformat(),
                    ReservationStatus.BOOKED.value,
                    table_slot.confirmation_code,
                    to_minutes_after_midnight(table_slot.ends_at),
                    to_minutes_after_midnight(table_slot.starts_at),
                ),
            ).fetchone()
            if overlapping_row is None:
                return candidate_table_id
        raise CandidateTablesTakenException(
            table_slot.reservation_date, table_slot.starts_at, {self._RESERVATION_DATE_CONTEXT_KEY: table_slot.reservation_date.isoformat()}
        )

    def _insert_reservation(
        self, connection: sqlite3.Connection, new_reservation: NewReservation, confirmation_code: str, table_id: str, now_utc: datetime
    ) -> None:
        connection.execute(
            f"""
            INSERT INTO reservations ({self._RESERVATION_COLUMNS}, created_at_utc, updated_at_utc)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,  # noqa: S608 - the interpolated column list is a class constant, never input
            (
                confirmation_code,
                new_reservation.guest_name,
                new_reservation.phone_number,
                new_reservation.party_size,
                new_reservation.reservation_date.isoformat(),
                to_minutes_after_midnight(new_reservation.starts_at),
                to_minutes_after_midnight(new_reservation.ends_at),
                table_id,
                new_reservation.notes,
                ReservationStatus.BOOKED.value,
                now_utc.isoformat(),
                now_utc.isoformat(),
            ),
        )

    def _update_reservation_schedule(
        self, connection: sqlite3.Connection, reservation_reschedule: ReservationReschedule, table_id: str, now_utc: datetime
    ) -> None:
        # The manager decided the change from the booking it read on another connection. The row is rewritten only
        # while it still holds that schedule, so a change committed in between is never silently overwritten.
        current_booked_schedule: BookedSchedule = reservation_reschedule.current_booked_schedule
        # notes is the one nullable column: in SQLite `notes = ?` is NULL rather than true when both sides are NULL, so
        # `IS` is required for a booking without notes to still match the schedule it was read with.
        update_cursor: sqlite3.Cursor = connection.execute(
            """
            UPDATE reservations
            SET party_size = ?, reservation_date = ?, starts_at_minutes = ?, ends_at_minutes = ?, table_id = ?, notes = ?, updated_at_utc = ?
            WHERE confirmation_code = ? AND status = ?
              AND party_size = ? AND reservation_date = ? AND starts_at_minutes = ? AND ends_at_minutes = ? AND table_id = ? AND notes IS ?
            """,
            (
                reservation_reschedule.party_size,
                reservation_reschedule.reservation_date.isoformat(),
                to_minutes_after_midnight(reservation_reschedule.starts_at),
                to_minutes_after_midnight(reservation_reschedule.ends_at),
                table_id,
                reservation_reschedule.notes,
                now_utc.isoformat(),
                reservation_reschedule.confirmation_code,
                ReservationStatus.BOOKED.value,
                current_booked_schedule.party_size,
                current_booked_schedule.reservation_date.isoformat(),
                to_minutes_after_midnight(current_booked_schedule.starts_at),
                to_minutes_after_midnight(current_booked_schedule.ends_at),
                current_booked_schedule.table_id,
                current_booked_schedule.notes,
            ),
        )
        if update_cursor.rowcount != 1:
            raise self._create_lost_reschedule_exception(connection, reservation_reschedule.confirmation_code)

    def _create_lost_reschedule_exception(
        self, connection: sqlite3.Connection, confirmation_code: str
    ) -> ReservationNotFoundException | ReservationChangedConcurrentlyException:
        """Why the conditional rewrite matched no row: the booking was cancelled since it was read, or it was changed."""
        still_booked_row: sqlite3.Row | None = connection.execute(
            "SELECT 1 FROM reservations WHERE confirmation_code = ? AND status = ?", (confirmation_code, ReservationStatus.BOOKED.value)
        ).fetchone()
        if still_booked_row is None:
            return ReservationNotFoundException(confirmation_code, {self._CONFIRMATION_CODE_CONTEXT_KEY: confirmation_code})
        return ReservationChangedConcurrentlyException(confirmation_code, {self._CONFIRMATION_CODE_CONTEXT_KEY: confirmation_code})

    def _read_reservation(self, connection: sqlite3.Connection, confirmation_code: str) -> Reservation:
        reservation_row: sqlite3.Row | None = connection.execute(
            f"SELECT {self._RESERVATION_COLUMNS} FROM reservations WHERE confirmation_code = ?",  # noqa: S608 - constant column list
            (confirmation_code,),
        ).fetchone()
        if reservation_row is None:
            raise RestaurantStoreContractViolationException(
                message=f"Reservation '{confirmation_code}' was written in this transaction but cannot be read back",
                contextual_data_by_name={self._CONFIRMATION_CODE_CONTEXT_KEY: confirmation_code},
            )
        return self._map_reservation_row(reservation_row)

    @staticmethod
    def _run_in_immediate_transaction[TResult](connection: sqlite3.Connection, write_operation: Callable[[], TResult]) -> TResult:
        connection.execute("BEGIN IMMEDIATE")
        try:
            write_result: TResult = write_operation()
            connection.execute("COMMIT")
        except BaseException:
            # SQLite rolls some failed transactions back by itself; a second ROLLBACK would raise and hide the first error.
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        return write_result

    @staticmethod
    def _map_seating_row(seating_row: sqlite3.Row) -> Seating:
        return Seating(
            confirmation_code=seating_row["confirmation_code"],
            table_id=seating_row["table_id"],
            starts_at=from_minutes_after_midnight(seating_row["starts_at_minutes"]),
            ends_at=from_minutes_after_midnight(seating_row["ends_at_minutes"]),
        )

    @staticmethod
    def _map_reservation_row(reservation_row: sqlite3.Row) -> Reservation:
        return Reservation(
            confirmation_code=reservation_row["confirmation_code"],
            guest_name=reservation_row["guest_name"],
            phone_number=reservation_row["phone_number"],
            party_size=reservation_row["party_size"],
            reservation_date=date.fromisoformat(reservation_row["reservation_date"]),
            starts_at=from_minutes_after_midnight(reservation_row["starts_at_minutes"]),
            ends_at=from_minutes_after_midnight(reservation_row["ends_at_minutes"]),
            table_id=reservation_row["table_id"],
            notes=reservation_row["notes"],
            reservation_status=ReservationStatus(reservation_row["status"]),
        )
