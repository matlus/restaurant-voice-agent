# The web host and the packages it uses, installed from the lock file into one slim image.
FROM python:3.14-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.5 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY packages packages
COPY apps apps
RUN uv sync --frozen --no-dev --no-editable --package voice-agent-web

FROM python:3.14-slim
RUN useradd --create-home --uid 10001 voiceagent
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
RUN mkdir /app/data && chown voiceagent /app/data
USER voiceagent
# The SQLite store lives inside the container, so it is seeded afresh whenever a new replica starts.
ENV PATH="/app/.venv/bin:$PATH" \
    VOICE_AGENT_WEB_HOST=0.0.0.0 \
    VOICE_AGENT_WEB_PORT=8000 \
    VOICE_AGENT_RESTAURANT_DATABASE_PATH=/app/data/restaurant.sqlite3
EXPOSE 8000
CMD ["voice_agent_web"]
