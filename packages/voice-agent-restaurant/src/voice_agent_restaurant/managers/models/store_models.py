from enum import StrEnum


class StoreSeeding(StrEnum):
    """What a new store is seeded with. The restaurant itself (profile, hours, closures, tables and menu) is always
    seeded; the demo bookings fill some of its tables so a demo has something to find, change and cancel."""

    RESTAURANT_ONLY = "restaurant_only"
    RESTAURANT_AND_DEMO_BOOKINGS = "restaurant_and_demo_bookings"
