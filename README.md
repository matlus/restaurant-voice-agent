# Restaurant Voice Agent

A real-time voice agent for a fictional restaurant, **Ember & Sprout**. You press a microphone button in a
browser, talk, and hear the agent answer in real time. It can describe the menu, answer ingredient, allergen,
calorie and diet questions, give opening hours, and check, book, change and cancel reservations.

The voice side will support two providers, chosen per session: the OpenAI Realtime API and the Gemini Live API.
See [docs/plan.md](docs/plan.md) for the full plan and what is built so far.

## Layout

| Path | What it is |
| --- | --- |
| `packages/voice-agent-restaurant` | The restaurant domain: profile, hours, menu, allergens, diets and reservations, behind one `DomainFacade`. No voice or web code. |
| `packages/voice-agent-restaurant/src/voice_agent_restaurant/seed_data` | The fictional restaurant: 32 dishes, hours, holiday closures, 15 tables and a few existing bookings. |
| `apps/voice-agent-web` | The web host (FastAPI and a one-button page). Not built yet. |

## The restaurant data

Every dish lists its ingredients, nutrition (calories, protein, carbohydrate, fat), the nine major US allergens it
contains (milk, eggs, fish, shellfish, tree nuts, peanuts, wheat, soy, sesame), and the diets it suits:

- **Lifestyle diets**, set by the recipe: vegan, vegetarian, pescatarian, keto, carnivore, paleo.
- **Free-from labels**, derived from the allergen data so they can never disagree with it: gluten-free, dairy-free,
  nut-free.

A test checks the whole menu for consistency, for example that every vegan dish is also vegetarian and contains no
milk or eggs, and that every keto dish stays at or under 15 g of carbohydrate.

The data lives in a local SQLite file. It is created and seeded the first time it is used. The seeded bookings land
on the coming Friday, Saturday and Sunday, and every 4-top is taken around 19:00 on Friday, so you can try a booking
that does not fit and hear the agent offer other times. Delete the file to start over.

## Getting started

You need [uv](https://docs.astral.sh/uv/) and Python 3.14.

```powershell
uv sync --all-packages --all-groups
Copy-Item .env.example .env
```

## Checks

Run these from the repository root before committing:

```powershell
uv run ruff check packages apps
uv run ruff format --check packages apps
uv run pyright
uv run pytest -q
```

## License

MIT
