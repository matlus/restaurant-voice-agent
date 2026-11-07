# voice-agent-restaurant

The restaurant domain for the voice agent. Everything goes through `DomainFacade`:

| Method | What it does |
| --- | --- |
| `get_restaurant_profile` | Name, address, phone, time zone, house notes and the reservation policy. |
| `get_restaurant_local_now` | The current date and time in the restaurant's time zone. |
| `get_opening_hours` | The weekly hours and the holiday closures inside the booking window. |
| `search_menu` | Dishes that suit every requested diet, contain none of the excluded allergens, and match an optional category, calorie ceiling and text. |
| `retrieve_dish` | One dish by its name or a distinctive part of it ("the salmon", "your scallops"). |
| `check_availability` | Whether a table fits the party at a time, with up to three nearby open times when it does not. |
| `create_reservation` | Books the smallest free table that fits and returns a six-character confirmation code. |
| `find_reservations` | Upcoming bookings for a phone number. |
| `change_reservation` | Changes date, time, party size or notes, given the confirmation code and phone number. |
| `cancel_reservation` | Cancels a booking, given the confirmation code and phone number. |

Requests arrive as plain values (dates as `YYYY-MM-DD`, times as 24-hour `HH:MM`), the way a voice model's tool call
supplies them. The validators normalize them (phone numbers to digits, confirmation codes to upper case, diet labels like
`Gluten-Free` to `gluten_free`) and validate them before anything else, reporting every problem in one exception.

A refusal raises a `VoiceAgentRestaurantBusinessBaseException` descendant whose message can be read to a guest.
Store or configuration trouble raises a `VoiceAgentRestaurantTechnicalBaseException` descendant, whose message must not.

## Configuration

| Variable | Meaning |
| --- | --- |
| `VOICE_AGENT_RESTAURANT_DATABASE_PATH` | Path of the SQLite file. It is created and seeded on first use. |
