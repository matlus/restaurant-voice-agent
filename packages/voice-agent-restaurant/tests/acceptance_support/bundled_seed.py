"""The bundled seed files a new store is created from, read into typed records so a test derives its expectations from
the seeded data itself."""

import json
from dataclasses import dataclass
from datetime import date, time
from importlib import resources
from typing import Any, Final

RESTAURANT_SEED_FILE_NAME: Final[str] = "restaurant.json"
TABLES_SEED_FILE_NAME: Final[str] = "tables.json"
MENU_SEED_FILE_NAME: Final[str] = "menu.json"
RESERVATIONS_SEED_FILE_NAME: Final[str] = "reservations.json"


@dataclass(frozen=True)
class SeededOpenWeekday:
    weekday: str
    opens_at: time
    closes_at: time


@dataclass(frozen=True)
class SeededClosedWeekday:
    weekday: str


type SeededWeekdayHours = SeededOpenWeekday | SeededClosedWeekday


@dataclass(frozen=True)
class SeededClosure:
    closed_on: date
    reason: str


@dataclass(frozen=True)
class SeededReservationPolicy:
    seating_duration_minutes: int
    slot_interval_minutes: int
    maximum_party_size: int
    booking_window_days: int


@dataclass(frozen=True)
class SeededRestaurant:
    name: str
    time_zone: str
    allergen_notice: str
    house_notes: list[str]
    weekly_hours: list[SeededWeekdayHours]
    closures: list[SeededClosure]
    reservation_policy: SeededReservationPolicy


@dataclass(frozen=True)
class SeededBookingGuest:
    """Who a seeded booking is under and the weekday the seed books it on."""

    guest_name: str
    weekday: str


@dataclass(frozen=True)
class SeededTable:
    table_id: str
    seats: int


@dataclass(frozen=True)
class SeededDish:
    dish_id: str
    name: str
    category: str
    description: str
    ingredients: list[str]
    allergens: list[str]
    contains_gluten: bool
    diets: list[str]
    calories: int


def read_seeded_restaurant() -> SeededRestaurant:
    restaurant_seed_object: dict[str, Any] = json.loads(_read_bundled_seed_text(RESTAURANT_SEED_FILE_NAME))
    reservation_policy_object: dict[str, Any] = restaurant_seed_object["reservation_policy"]
    return SeededRestaurant(
        name=restaurant_seed_object["name"],
        time_zone=restaurant_seed_object["time_zone"],
        allergen_notice=restaurant_seed_object["allergen_notice"],
        house_notes=list(restaurant_seed_object["house_notes"]),
        weekly_hours=[
            _to_seeded_weekday_hours(hours_object["weekday"], hours_object["opens_at"], hours_object["closes_at"])
            for hours_object in restaurant_seed_object["weekly_hours"]
        ],
        closures=[
            SeededClosure(closed_on=date.fromisoformat(closure_object["closed_on"]), reason=closure_object["reason"])
            for closure_object in restaurant_seed_object["closures"]
        ],
        reservation_policy=SeededReservationPolicy(
            seating_duration_minutes=reservation_policy_object["seating_duration_minutes"],
            slot_interval_minutes=reservation_policy_object["slot_interval_minutes"],
            maximum_party_size=reservation_policy_object["maximum_party_size"],
            booking_window_days=reservation_policy_object["booking_window_days"],
        ),
    )


def read_seeded_tables() -> list[SeededTable]:
    tables_seed_object: dict[str, Any] = json.loads(_read_bundled_seed_text(TABLES_SEED_FILE_NAME))
    return [SeededTable(table_id=table_object["table_id"], seats=table_object["seats"]) for table_object in tables_seed_object["tables"]]


def read_seeded_dishes() -> list[SeededDish]:
    menu_seed_object: dict[str, Any] = json.loads(_read_bundled_seed_text(MENU_SEED_FILE_NAME))
    return [
        SeededDish(
            dish_id=dish_object["dish_id"],
            name=dish_object["name"],
            category=dish_object["category"],
            description=dish_object["description"],
            ingredients=list(dish_object["ingredients"]),
            allergens=list(dish_object["allergens"]),
            contains_gluten=dish_object["contains_gluten"],
            diets=list(dish_object["diets"]),
            calories=dish_object["nutrition"]["calories"],
        )
        for dish_object in menu_seed_object["dishes"]
    ]


def read_seeded_booking_guest(phone_number: str) -> SeededBookingGuest:
    reservations_seed_object: dict[str, Any] = json.loads(_read_bundled_seed_text(RESERVATIONS_SEED_FILE_NAME))
    seeded_booking_guests: list[SeededBookingGuest] = [
        SeededBookingGuest(guest_name=reservation_object["guest_name"], weekday=reservation_object["weekday"])
        for reservation_object in reservations_seed_object["reservations"]
        if reservation_object["phone_number"] == phone_number
    ]
    assert len(seeded_booking_guests) == 1, f"The seed must hold exactly one booking for {phone_number}; found {len(seeded_booking_guests)}"
    return seeded_booking_guests[0]


def _to_seeded_weekday_hours(weekday: str, opens_at: str | None, closes_at: str | None) -> SeededWeekdayHours:
    # The seed gives a closed day as null hours; the reader refuses a day with only one of the two.
    if opens_at is None or closes_at is None:
        return SeededClosedWeekday(weekday=weekday)
    return SeededOpenWeekday(weekday=weekday, opens_at=time.fromisoformat(opens_at), closes_at=time.fromisoformat(closes_at))


def _read_bundled_seed_text(seed_file_name: str) -> str:
    return resources.files("voice_agent_restaurant").joinpath("seed_data", seed_file_name).read_text(encoding="utf-8")
