import logging
import os
from typing import Final

import uvicorn
from dotenv import load_dotenv

from voice_agent_web.main import create_app

HOST_VARIABLE_NAME: Final[str] = "VOICE_AGENT_WEB_HOST"
PORT_VARIABLE_NAME: Final[str] = "VOICE_AGENT_WEB_PORT"
# Comma-separated origins, such as https://booking.example.com, of other sites whose pages may open a call.
ALLOWED_ORIGINS_VARIABLE_NAME: Final[str] = "VOICE_AGENT_WEB_ALLOWED_ORIGINS"
DEFAULT_HOST: Final[str] = "127.0.0.1"
DEFAULT_PORT: Final[int] = 8000


def main() -> None:
    # Keys live only in the gitignored .env; settings providers read the environment it fills.
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    allowed_origins: list[str] = [origin.strip() for origin in os.environ.get(ALLOWED_ORIGINS_VARIABLE_NAME, "").split(",") if origin.strip()]
    uvicorn.run(
        create_app(allowed_origins=allowed_origins),
        host=os.environ.get(HOST_VARIABLE_NAME, DEFAULT_HOST),
        port=int(os.environ.get(PORT_VARIABLE_NAME, str(DEFAULT_PORT))),
    )


if __name__ == "__main__":
    main()
