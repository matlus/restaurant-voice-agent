# voice-agent-restaurant

The restaurant domain for the voice agent. Everything goes through `DomainFacade`:

| Method | What it does |
| --- | --- |
| `get_restaurant_profile` | Name, address, phone, time zone, the shared-kitchen allergen notice, other house notes and the reservation policy. |
| `get_restaurant_local_now` | The current date and time in the restaurant's time zone. |
| `get_opening_hours` | The weekly hours and the holiday closures inside the booking window. |
| `search_menu` | Dishes that suit every requested diet, contain none of the excluded allergens, and match an optional category, calorie ceiling and text. Says whether the search was about allergy safety (it excluded allergens or asked for a free-from diet), which is when the allergen notice applies. |
| `retrieve_dish` | One dish by its name or a distinctive part of it ("the salmon", "your scallops"). |
| `check_availability` | Whether a table fits the party at a time, with up to three nearby open times when it does not. |
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
