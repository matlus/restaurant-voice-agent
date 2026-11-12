import logging
import os
from typing import Final

import uvicorn
from dotenv import load_dotenv

from voice_agent_web.json_log_formatter import JsonLogFormatter
from voice_agent_web.main import DEFAULT_MAXIMUM_CONCURRENT_CALLS, create_app

HOST_VARIABLE_NAME: Final[str] = "VOICE_AGENT_WEB_HOST"
PORT_VARIABLE_NAME: Final[str] = "VOICE_AGENT_WEB_PORT"
# Comma-separated origins, such as https://booking.example.com, of other sites whose pages may open a call.
ALLOWED_ORIGINS_VARIABLE_NAME: Final[str] = "VOICE_AGENT_WEB_ALLOWED_ORIGINS"
MAXIMUM_CONCURRENT_CALLS_VARIABLE_NAME: Final[str] = "VOICE_AGENT_MAXIMUM_CONCURRENT_CALLS"
DEFAULT_HOST: Final[str] = "127.0.0.1"
DEFAULT_PORT: Final[int] = 8000


def main() -> None:
    # Keys live only in the gitignored .env; settings providers read the environment it fills.
    load_dotenv()
    log_handler: logging.Handler = logging.StreamHandler()
    log_handler.setFormatter(JsonLogFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[log_handler])
    allowed_origins: list[str] = [origin.strip() for origin in os.environ.get(ALLOWED_ORIGINS_VARIABLE_NAME, "").split(",") if origin.strip()]
    maximum_concurrent_calls: int = int(os.environ.get(MAXIMUM_CONCURRENT_CALLS_VARIABLE_NAME, str(DEFAULT_MAXIMUM_CONCURRENT_CALLS)))
    uvicorn.run(
        create_app(allowed_origins=allowed_origins, maximum_concurrent_calls=maximum_concurrent_calls),
        host=os.environ.get(HOST_VARIABLE_NAME, DEFAULT_HOST),
        port=int(os.environ.get(PORT_VARIABLE_NAME, str(DEFAULT_PORT))),
        # "on" makes a failure while the app starts up stop the process; "auto" would log it and keep serving.
        lifespan="on",
        # The root handler above formats uvicorn's own lines too; uvicorn's default config would give them plain-text handlers.
        log_config=None,
    )


if __name__ == "__main__":
    main()
