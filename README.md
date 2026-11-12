# Restaurant Voice Agent

A voice agent that answers the phone for a fictional restaurant, **Ember & Sprout**. You open a page in your browser,
press the call button and talk. The agent answers out loud, in real time, like a host picking up the phone. It answers
questions about the menu, diets, allergens and opening hours, and it checks availability and books, finds, changes and
cancels reservations. Every answer comes from the restaurant's own data, never from the model's imagination.

It runs locally or on Azure Container Apps, on the OpenAI Realtime API. Support for a second voice provider and for hosting on a telephony
platform are planned (see [What's next](#whats-next)).

## What a caller can do

### Ask about the food

- **Find dishes for a diet:** vegan, vegetarian, pescatarian, keto, carnivore or paleo, plus gluten-free, dairy-free
  and nut-free. Ask "What do you have that's keto?" and the agent names two or three that fit best, then offers more.
- **Avoid allergens:** the nine major US allergens (milk, eggs, fish, shellfish, tree nuts, peanuts, wheat, soy and
  sesame). Ask for dishes without sesame, or whether a dish has nuts. Whenever an answer is about an allergen or a
  free-from diet, the agent also says, once in the call, that everything is made in a shared kitchen, so no dish is
  guaranteed free of traces, and suggests telling the server about any allergy.
- **Narrow it down:** by menu section (starters, garden, mains, sides, desserts, drinks), by a calorie limit, or by a
  word such as "salmon" or "mushroom".
- **Hear about one dish:** what's in it, its price, calories, protein, carbohydrate and fat, its allergens and any
  shared-kitchen (cross-contact) note. A dish can be named loosely, like "the ribeye" or "your scallops".

### Ask about hours

The agent gives the weekly hours and any holiday closures in the coming weeks. It says times the way people do on the
phone, like "5 to 10 PM", not "17:00".

### Book a table

- **Check availability** for a date, time and party size. If nothing fits, the agent offers up to three of the nearest
  open times that day. If the day is fully booked, it says so.
- **Book** with a name and phone number. Before booking, the agent checks the details in one short line and waits for
  a yes. It then gives a six-character confirmation code, slowly, one character at a time.
- **Find bookings** by the phone number, name and date they are under, for a caller who doesn't have their code.
- **Change** the date, time, party size or notes of a booking, or remove its notes.
- **Cancel** a booking.

To change or cancel, the confirmation code alone is enough. A caller who doesn't have it gives the phone number, the
name (the family name, or any name after the first, is enough) and the date the booking is under, and the agent looks it up. A phone number alone
reveals nothing, and a lookup never gives out the confirmation code. Tool answers carry only what the agent must say:
no table numbers, phone numbers or guest notes. If a request can't be done, for example because the restaurant is closed that day or
the time is too close to closing, the agent explains why in plain words and offers what the restaurant suggests.

### How the agent talks

The agent is meant to sound like a relaxed person who works there, not a call center. Replies are short, usually one
sentence. It uses everyday words, avoids stiff phrases like "Certainly!" or "I'd be happy to assist", and asks one
thing at a time. A caller can interrupt at any point, and the agent stops talking and listens.

The agent knows the restaurant's current local date and time, so "tonight" or "this Friday" resolve to the right date.

Four voices are available, picked on the page before a call: Marin and Coral (female), and Cedar and Ash (male).

## Try it: test scenarios

The seed data sets up situations worth calling about. The demo bookings are seeded only when
`VOICE_AGENT_RESTAURANT_STORE_SEEDING` is `restaurant_and_demo_bookings`, as it is in `.env.example` and the hosted demo. They land on the
next occurrence of their weekday after the store is created (today counts), so the scenarios stay in the future.

| Scenario | What to try |
| --- | --- |
| Busy Friday evening | Every 4-person table is taken around 7 PM. Ask for four at 7 and hear other times offered. A party of two still fits. |
| Fully booked Tuesday | Every table is taken all evening. Any request gets "nothing available that day". |
| Nearly full Wednesday | Only 6:30 PM and 8:30 PM are left, for up to four people. Ask for 7 and hear those two offered. |
| Closed Monday | The restaurant doesn't open on Mondays. |
| Holidays | Closed on Thanksgiving, Christmas Eve, Christmas Day and New Year's Day 2026–27. These are fixed dates in `seed_data/restaurant.json`, unlike the bookings, so after January 1, 2027 this scenario has no closure left until the dates there are moved on. |
| Existing booking | Priya Raman has a Friday booking under phone number 555-010-1001, confirmation code `KX4TPA`. Change or cancel it with the code, or by phone number, name and date. |
| Large party | Parties over eight are pointed to the private dining room instead. |

The store is disposable. To start over with fresh data, stop the app and delete the SQLite file
(`data/restaurant.sqlite3` by default); it is created and seeded again on the next run. A store created by another
version of the app is not migrated: the app refuses it at startup with a message saying so, and you delete it the same
way.

## The restaurant

Ember & Sprout is "a modern grill and garden kitchen" at 418 Juniper Street, Riverton, Illinois, in the Central time
zone. It opens Tuesday to Thursday 5–10 PM, Friday 5–11 PM, Saturday noon–11 PM and Sunday 11 AM–9 PM.

- **Menu:** 32 dishes across starters, garden plates, mains, sides, desserts and drinks. Every dish lists its
  ingredients, nutrition, allergens and the diets it suits.
- **Diet labels:** the lifestyle diets (vegan, vegetarian, pescatarian, keto, carnivore, paleo) come from the recipe.
  The free-from labels (gluten-free, dairy-free, nut-free) are derived from the allergen data, so the two can never
  disagree. They describe the recipe, not cross-contact, which is why the agent always gives the shared-kitchen
  allergen notice with them. A test checks the whole menu for consistency: for example, every vegan dish is also vegetarian and
  contains no milk or eggs, and every keto dish has at most 15 g of carbohydrate.
- **Tables:** 15 tables, from 2 to 8 seats, in the window, main room and garden room.
- **Reservation rules:** a seating lasts 90 minutes. Bookable times fall every 15 minutes, and a seating must end by
  closing time. Parties are 1 to 8 people, and bookings open up to 60 days ahead. A booking takes the smallest free
  table that fits the party.

## How it works

```text
Browser page: call button, voice choice, microphone audio
   |  WebSocket /conversation: 16-bit PCM audio up; agent audio and JSON events down
Web host (apps/voice-agent-web, FastAPI)
   |
Conversation domain (packages/voice-agent-conversation)
   |  realtime voice gateway                 agent toolbox (8 tools)
   +--> OpenAI Realtime API                  +--> Restaurant domain (packages/voice-agent-restaurant)
        speech in, speech out                          |
        asks for tool calls                       SQLite, seeded from JSON
```

A call goes like this:

1. The page opens a WebSocket to the host with the chosen voice. The host calls the conversation domain once and
   relays everything in both directions.
2. The conversation domain opens a session with the speech model. The session carries the agent's instructions (its
   role, how to talk, the restaurant's local date and time) and the eight tool definitions.
3. Audio streams both ways as it is spoken. Turn detection decides when the caller has finished: the turn ends after
   half a second of silence. When the caller talks over the agent, the page stops playback at once ("barge-in")
   and reports how much speech it dropped, so the agent forgets what the caller never heard.
4. When the model needs a fact, it asks for a **tool call**, which means it names a tool and passes arguments as JSON.
   The toolbox checks the arguments, runs the tool against the restaurant domain, and sends the result back. The model
   then answers out loud. If the caller is talking when the tool calling reply ends, the domain does not ask for that
   answer itself: turn detection asks for it when the caller finishes, so the agent does not talk over them.
5. The speech provider reports most errors without closing the session. A short allow-list of errors known to be
   harmless is logged by the host and the call goes on; any other error ends the call. When a session reaches the
   provider's time limit, the caller is told the call has ended and to call again.

### The tools

| Tool | What it does |
| --- | --- |
| `search_menu` | Dishes matching diets, excluded allergens, section, calorie limit and search words. A search about an allergy also carries the restaurant's allergen notice. |
| `describe_dish` | One dish in full, found by a loose name, with the restaurant's allergen notice. |
| `get_opening_hours` | Weekly hours and upcoming holiday closures. |
| `check_availability` | Whether a table fits, with nearby open times when it doesn't. Given the caller's own booking code, that booking's table counts as free. |
| `book_table` | Books a table and returns the confirmation code. |
| `find_bookings` | The times and party sizes of a caller's bookings on one date, found by phone number, name and date. |
| `change_booking` | Changes date, time, party size or notes of a booking found by its confirmation code. |
| `change_booking_by_details` | The same change, for a caller without the code: the booking is found by phone number, name, date and time. |
| `cancel_booking` | Cancels a booking found by its confirmation code. |
| `cancel_booking_by_details` | Cancels a booking found by phone number, name, date and time. |

Each tool is a standalone class with a Pydantic input model. Pydantic is a validation library, and here it also
produces the JSON schema that tells the model what arguments the tool takes. The toolbox treats three outcomes
differently:

- **A refusal from the restaurant**, such as "closed that day", "no table free" or "parties over eight book the
  private dining room", comes back to the model as an answer with the reason, which the agent relays to the caller.
  It is not an error, and it never counts as a malformed call.
- **A malformed call**, such as an unknown tool, bad arguments or a value the restaurant can't read, goes back to the
  model with what was wrong so it can correct itself without mentioning it to the caller. Three malformed calls in a
  row are allowed; a fourth with nothing accepted in between ends the conversation with an error.
- **A technical failure**, such as a database error, ends the conversation and is logged.

## Repository layout

This is a [uv](https://docs.astral.sh/uv/) workspace: one repository holding several Python packages that are
developed together.

| Path | What it is |
| --- | --- |
| `packages/voice-agent-restaurant` | The restaurant domain: profile, hours, menu, diets, allergens and reservations, behind one `DomainFacade`. Knows nothing about voice or the web. Includes the seed data in `seed_data/`. |
| `packages/voice-agent-conversation` | Voice conversations: the speech-provider gateway, the agent's instructions, the voice catalog and the agent tools, behind one `DomainFacade`. |
| `apps/voice-agent-web` | The web host: a FastAPI app with the page, `GET /voices` and the `/conversation` WebSocket. |
| `docs/plan.md` | The original plan and design decisions. |

Each package has its own README with more detail.

## Getting started

You need [uv](https://docs.astral.sh/uv/), Python 3.14 and an OpenAI API key with access to the Realtime API.

```bash
uv sync --all-packages --all-groups
cp .env.example .env
```

Put your OpenAI key in `.env` as `OPENAI_API_KEY`. `.env` is gitignored; never put a real key in `.env.example`. Then
start the app:

```bash
uv run --all-packages voice_agent_web
```

Open http://127.0.0.1:8000, choose a voice and press the call button. The browser asks for microphone access once.
Browsers give a page the microphone only over HTTPS or on `localhost`/`127.0.0.1`, so a deployed app must be served
over HTTPS.

### Settings

| Variable | Required | What it sets |
| --- | --- | --- |
| `OPENAI_API_KEY` | Yes | Your OpenAI API key. |
| `VOICE_AGENT_RESTAURANT_DATABASE_PATH` | Yes | Where the SQLite store lives, such as `data/restaurant.sqlite3`. Created and seeded if missing. |
| `VOICE_AGENT_RESTAURANT_STORE_SEEDING` | No | `restaurant_and_demo_bookings` seeds a new store with the demo bookings the test scenarios use. Defaults to `restaurant_only`, so a real deployment starts with no bookings. |
| `VOICE_AGENT_OPENAI_REALTIME_MODEL` | No | The speech model. Defaults to `gpt-realtime-2.1`. `gpt-realtime-2.1-mini` costs less. |
| `VOICE_AGENT_OPENAI_REALTIME_WEBSOCKET_BASE_URL` | No | Another Realtime address. Tests use this to point at a scripted service. |
| `VOICE_AGENT_WEB_HOST` / `VOICE_AGENT_WEB_PORT` | No | Where the web app listens. Defaults to `127.0.0.1` and `8000`. A port that is not a whole number from 1 to 65535 stops startup with a message naming it. |
| `VOICE_AGENT_WEB_ALLOWED_ORIGINS` | No | Comma-separated origins of other sites whose pages may open a call, such as `https://booking.example.com`. The app's own page is always allowed. |
| `VOICE_AGENT_MAXIMUM_CALL_SECONDS` | No | The longest a call lasts before the agent says goodbye. Defaults to `900` (15 minutes). |
| `VOICE_AGENT_MAXIMUM_SILENCE_SECONDS` | No | How long the caller may stay silent before the agent says goodbye. Defaults to `120`. |
| `VOICE_AGENT_MAXIMUM_CONCURRENT_CALLS` | No | How many calls one process runs at once; a further caller is told all lines are busy. Defaults to `10`. |

### Limits and security

Every open call holds a paid OpenAI Realtime session, so the app bounds what a call can cost:

- A call ends with a short spoken goodbye once it reaches the maximum length or the caller has been silent too long.
  The page then shows why the call ended.
- Only so many calls run at once. A caller beyond the limit is told all lines are busy and the socket closes with
  code `1013` (try again later).
- Guest audio pieces larger than 200 ms are dropped, and so is audio arriving faster than it could be spoken (beyond
  a one-second burst). The page sends 50 ms pieces in real time, so it never loses any.
- Browsers do not apply the same-origin policy to WebSockets and send the site's cookies with the handshake. The app
  refuses a `/conversation` handshake whose `Origin` is neither its own host nor in `VOICE_AGENT_WEB_ALLOWED_ORIGINS`,
  so a page on another site cannot open a call from a signed-in user's browser, whatever the sign-in cookie's
  `SameSite` setting is.

### Logs

The app logs one JSON object per line. Every call ends with a `call_ended` entry: its `conversation_id`, voice, length,
how it ended (`hung_up`, `call_limit:…` or `failed`) and the agent's tool calls by name and outcome. Nothing the caller
said is logged. A failure is logged once, with the conversation id in its context: a business refusal as a warning, a
fault as an error. Messages that reach the log do not repeat phone numbers. `GET /healthz` answers once the store can
be read.

**The image has no authentication of its own.** The Dockerfile binds `0.0.0.0`, and on Azure the Container Apps
sign-in stands in front of it. Run the image anywhere without a sign-in in front and anyone who can reach it can spend
the OpenAI key and change bookings. Also set a monthly spend limit on the OpenAI project, as a backstop the app cannot
enforce.

## Development

### Checks

Run these from the repository root before committing:

```bash
uv run --all-packages --all-groups ruff check .
uv run --all-packages --all-groups ruff format --check .
uv run --all-packages --all-groups pyright
uv run --all-packages --all-groups pytest -q --cov
```

The `--cov` run fails if line coverage drops below the floor set in `pyproject.toml`. CI (`.github/workflows/ci.yml`)
runs the same four checks, plus a `docker build`, on every pull request and every push to `main`. Dependabot proposes
updates to the lock file, the base images (pinned by digest in the `Dockerfile`) and the workflow actions.

### Tests

There are over 200 tests, and they never call OpenAI. Most are acceptance tests: they drive each package through its
public `DomainFacade` the way a real caller would, against a real SQLite store seeded from the bundled data. For voice,
the real OpenAI gateway connects over a real WebSocket to a scripted Realtime service that the tests run on the local
machine. That service plays back the events a real session would send, including tool calls, and records what the
gateway sent in reply.

### How the code is organized

The code follows Programming with Intent (PWI), a set of design and review guidelines. In short:

- Each package exposes one `DomainFacade` as its only public entry point. Hosts stay thin: the web app reads the
  request, calls the facade once and relays the result. Business rules never live in the host.
- Inside a package, managers coordinate the work, validators check every input first, and data managers and gateways
  talk to SQLite and to OpenAI. A service locator wires these together, and tests swap in their own pieces through it.
- Every exception derives from a business or technical base exception. Exceptions are logged only at the host's
  boundary, and a technical error's details never reach the caller.
- Everything from the host down is async.

## Deploying to Azure

The app runs on Azure Container Apps as a single container built from the `Dockerfile` at the root. Everything lives
in one resource group, `rg-restaurant-voice-agent`, in Central US:

| Resource | Name | Purpose |
| --- | --- | --- |
| Container registry (Basic) | `crrestaurantvoiceagent` | Holds the image. The app pulls it with its managed identity, so there are no registry passwords. |
| Container Apps environment | `cae-restaurant-voice-agent` | The hosting environment, with a Log Analytics workspace for logs. |
| Container app | `ca-restaurant-voice-agent` | The web host: 0.5 vCPU, 1 GiB, scales to zero when idle and to at most one replica. |
| Entra app registration | `Restaurant Voice Agent` | Container Apps authentication sends visitors to Microsoft sign-in. Only users assigned to the app can get in. |

The OpenAI key is a Container Apps secret, `openai-api-key`, and never goes into the image. The SQLite store lives
inside the container, so it is seeded afresh whenever a new replica starts, for example after the app scales to zero.

To ship a new version, build and push an image tagged with the commit, then point the app at it:

```bash
az acr login -n crrestaurantvoiceagent
docker build -t crrestaurantvoiceagent.azurecr.io/voice-agent-web:$(git rev-parse --short HEAD) .
docker push crrestaurantvoiceagent.azurecr.io/voice-agent-web:$(git rev-parse --short HEAD)
az containerapp update -g rg-restaurant-voice-agent -n ca-restaurant-voice-agent --image crrestaurantvoiceagent.azurecr.io/voice-agent-web:$(git rev-parse --short HEAD)
```

To give someone else access, assign them to the `Restaurant Voice Agent` enterprise application in Entra ID. To tear
everything down, delete the resource group and the app registration.

## What's next

- **Restaurant details by voice:** the address, phone number, parking and accessibility notes are in the data, but no
  tool exposes them to the agent yet.
- **Gemini Live** as a second speech provider, chosen per call.
- **Hosting on a telephony platform** (Vapi), so the agent answers a real phone number, with the same restaurant
  operations exposed as HTTP tool endpoints.

Today the app is a demo. It sends no confirmation texts or emails, and keeps its data in a SQLite file that the hosted
copy loses whenever it restarts. Real use needs a server database (Postgres or Azure SQL) for bookings; the data
managers already hide the store, so that change stays inside them.

## License

MIT
