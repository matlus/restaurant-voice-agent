# voice-agent-restaurant

The restaurant domain for the voice agent. Everything goes through `DomainFacade`:

| Method | What it does |
| --- | --- |
| `get_restaurant_profile` | Name, address, phone, time zone, the shared-kitchen allergen notice, other house notes and the reservation policy. |
| `get_restaurant_local_now` | The current date and time in the restaurant's time zone. |
| `get_opening_hours` | The weekly hours and the holiday closures inside the booking window. |
| `search_menu` | Dishes that suit every requested diet, contain none of the excluded allergens, and match an optional category, calorie ceiling and text. Says whether the search was about allergy safety (it excluded allergens or asked for a free-from diet), which is when the allergen notice applies. |
| `retrieve_dish` | One dish by its name or a distinctive part of it ("the salmon", "your scallops"). |
| `check_availability` | Whether a table fits the party at a time, with up to three nearby open times when it does not. An optional confirmation code leaves that booking's own table out, for a caller asking about moving it. |
| `create_reservation` | Books the smallest free table that fits and returns a six-character confirmation code. |
| `find_reservations` | Upcoming bookings on one date that match a phone number and the name they are under (any name after the first is enough). |
| `change_reservation` | Changes date, time, party size or notes. The booking is found by its confirmation code (a phone number given with it must match), or by the phone number, name, date and time it is booked under. |
| `cancel_reservation` | Cancels a booking, found the same way as for a change. |

Requests arrive as plain values (dates as `YYYY-MM-DD`, times as 24-hour `HH:MM` or as spoken, like `6:30 PM`), the
way a voice model's tool call supplies them. The validators normalize them (phone numbers to digits, confirmation codes
to upper case, diet labels like `Gluten-Free` to `gluten_free`) and validate them before anything else, reporting every
problem in one `ReservationRequestValidationException` (or its menu equivalent). A request that reads well but breaks
the booking policy, such as a party over eight, a time that has passed or a time between bookable times, raises
`ReservationPolicyRefusedException` instead, with every reason together. Callers rarely say AM or PM, so a morning
time the restaurant can't seat is read as the same time in the evening when that one can be seated.

A refusal raises a `VoiceAgentRestaurantBusinessBaseException` descendant whose message can be read to a guest.
Store or configuration trouble raises a `VoiceAgentRestaurantTechnicalBaseException` descendant, whose message must not.

## Configuration

| Variable | Meaning |
| --- | --- |
| `VOICE_AGENT_RESTAURANT_DATABASE_PATH` | Path of the SQLite file. It is created and seeded on first use. |
| `VOICE_AGENT_RESTAURANT_STORE_SEEDING` | `restaurant_and_demo_bookings` also seeds the demo bookings; `restaurant_only` (the default) seeds only the restaurant: profile, hours, closures, tables and menu. |

## The store

The store is a single SQLite file and is disposable: it holds the bundled seed and the bookings made since. A store
created by another version of the app is refused at startup, with a message saying to delete it; there are no
migrations. A store is only created in a new, empty file: a path that holds some other program's SQLite database is
refused and the file is left untouched. The file uses write-ahead logging, so lookups carry on while a booking is written, and its own `CHECK`
constraints refuse impossible rows (no guests, a seating that ends before it starts, an unknown status) even if the
domain's validation were bypassed. Two bookings racing for the last fitting table cannot both win: each seats its
party inside one `IMMEDIATE` transaction, and a test proves exactly one succeeds.

The restaurant's reference data (profile, hours, closures, tables and menu) never changes while the app runs, so it
is read once when the `DomainFacade` is built and served from memory after that. A booking then reads the store only
for the bookings it must check and the one it writes.
