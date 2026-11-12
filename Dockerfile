# The web host and the packages it uses, installed from the lock file into one slim image.
# Base images are pinned by digest so a build is repeatable; Dependabot proposes the updates.
FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928 AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.5@sha256:32a7bb39b496babbd997b0a39a4d66c126bdaf5661b302bf6f06abda8deca6ff /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY packages packages
COPY apps apps
RUN uv sync --frozen --no-dev --no-editable --package voice-agent-web

FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928
RUN useradd --create-home --uid 10001 voiceagent
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
RUN mkdir /app/data && chown voiceagent /app/data
USER voiceagent
# The SQLite store lives inside the container, so it is seeded afresh whenever a new replica starts. This image is the
# hosted demo, so it seeds the demo bookings the test scenarios rely on; a real deployment leaves them out.
ENV PATH="/app/.venv/bin:$PATH" \
    VOICE_AGENT_WEB_HOST=0.0.0.0 \
    VOICE_AGENT_WEB_PORT=8000 \
    VOICE_AGENT_RESTAURANT_DATABASE_PATH=/app/data/restaurant.sqlite3 \
    VOICE_AGENT_RESTAURANT_STORE_SEEDING=restaurant_and_demo_bookings
EXPOSE 8000
CMD ["voice_agent_web"]
