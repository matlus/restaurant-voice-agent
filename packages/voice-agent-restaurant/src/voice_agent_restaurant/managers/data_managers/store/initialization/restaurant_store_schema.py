from typing import Final

from voice_agent_restaurant.managers.models.reservation_models import ReservationStatus

# The store's version lives in SQLite's PRAGMA user_version. A new, empty file reads 0; a created and seeded store reads this.
# The store is disposable: it holds the bundled seed and the bookings made since, and a store from another version is
# refused rather than migrated, so it is deleted and created again.
STORE_VERSION: Final[int] = 3

# The status values the reservations table accepts, from the one enum that defines them.
_RESERVATION_STATUS_VALUES: Final[str] = ", ".join(f"'{reservation_status.value}'" for reservation_status in ReservationStatus)

# Times of day are stored as minutes after midnight and dates as ISO text, so range
# comparisons in SQL are plain integer and string comparisons.
SCHEMA_STATEMENTS: Final[tuple[str, ...]] = (
    """
    CREATE TABLE IF NOT EXISTS restaurant (
        restaurant_id INTEGER PRIMARY KEY CHECK (restaurant_id = 1),
        name TEXT NOT NULL,
        tagline TEXT NOT NULL,
        description TEXT NOT NULL,
        street_address TEXT NOT NULL,
        city TEXT NOT NULL,
        state_or_region TEXT NOT NULL,
        postal_code TEXT NOT NULL,
        phone_number TEXT NOT NULL,
        time_zone TEXT NOT NULL,
        allergen_notice TEXT NOT NULL,
        house_notes_json TEXT NOT NULL,
        seating_duration_minutes INTEGER NOT NULL,
        slot_interval_minutes INTEGER NOT NULL,
        minimum_party_size INTEGER NOT NULL,
        maximum_party_size INTEGER NOT NULL,
        booking_window_days INTEGER NOT NULL,
        late_arrival_hold_minutes INTEGER NOT NULL,
        large_party_guidance TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS weekly_hours (
        weekday_index INTEGER PRIMARY KEY CHECK (weekday_index BETWEEN 0 AND 6),
        opens_at_minutes INTEGER NULL,
        closes_at_minutes INTEGER NULL,
        CHECK ((opens_at_minutes IS NULL) = (closes_at_minutes IS NULL))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS closures (
        closed_on TEXT PRIMARY KEY,
        reason TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS dining_tables (
        table_id TEXT PRIMARY KEY,
        seats INTEGER NOT NULL,
        area TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS dishes (
        dish_id TEXT PRIMARY KEY,
        menu_position INTEGER NOT NULL,
        name TEXT NOT NULL,
        category TEXT NOT NULL,
        description TEXT NOT NULL,
        price_cents INTEGER NOT NULL,
        contains_gluten INTEGER NOT NULL,
        calories INTEGER NOT NULL,
        protein_grams INTEGER NOT NULL,
        carbohydrate_grams INTEGER NOT NULL,
        fat_grams INTEGER NOT NULL,
        cross_contact_note TEXT NULL,
        ingredients_json TEXT NOT NULL,
        allergens_json TEXT NOT NULL,
        recipe_diet_labels_json TEXT NOT NULL
    )
    """,
    f"""
    CREATE TABLE IF NOT EXISTS reservations (
        confirmation_code TEXT PRIMARY KEY,
        guest_name TEXT NOT NULL,
        phone_number TEXT NOT NULL,
        party_size INTEGER NOT NULL CHECK (party_size > 0),
        reservation_date TEXT NOT NULL,
        starts_at_minutes INTEGER NOT NULL CHECK (starts_at_minutes BETWEEN 0 AND 1439),
        ends_at_minutes INTEGER NOT NULL CHECK (ends_at_minutes <= 1440),
        table_id TEXT NOT NULL REFERENCES dining_tables (table_id),
        notes TEXT NULL,
        status TEXT NOT NULL CHECK (status IN ({_RESERVATION_STATUS_VALUES})),
        created_at_utc TEXT NOT NULL,
        updated_at_utc TEXT NOT NULL,
        CHECK (ends_at_minutes > starts_at_minutes)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_reservations_date ON reservations (reservation_date, status)",
    "CREATE INDEX IF NOT EXISTS ix_reservations_table ON reservations (table_id)",
    "CREATE INDEX IF NOT EXISTS ix_reservations_phone ON reservations (phone_number, status)",
)
