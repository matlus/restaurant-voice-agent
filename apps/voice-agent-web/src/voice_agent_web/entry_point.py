import logging
import os

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI

from voice_agent_conversation import ConfigurationSettingException as ConversationConfigurationSettingException
from voice_agent_restaurant import ConfigurationSettingException as RestaurantConfigurationSettingException
from voice_agent_web.configuration_providers.host_settings import HostSettings
from voice_agent_web.configuration_providers.host_settings_provider import HostSettingsProvider
from voice_agent_web.exceptions.host_setting_exception import HostSettingException
from voice_agent_web.json_log_formatter import JsonLogFormatter
from voice_agent_web.main import create_app
from voice_agent_web.validators.validator_host_settings import ValidatorHostSettings


def main() -> None:
    # Keys live only in the gitignored .env; settings providers read the environment it fills.
    load_dotenv()
    log_handler: logging.Handler = logging.StreamHandler()
    log_handler.setFormatter(JsonLogFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[log_handler])
    try:
        host_settings: HostSettings = HostSettingsProvider(os.environ).get_host_settings()
        port: int = ValidatorHostSettings.validate_port(host_settings.port)
        app: FastAPI = create_app(allowed_origins=host_settings.allowed_origins, maximum_concurrent_calls=host_settings.maximum_concurrent_calls)
    except (HostSettingException, ConversationConfigurationSettingException, RestaurantConfigurationSettingException) as setting_exception:
        # A setting the operator must fix: its message says which and how, so a traceback would only bury it.
        logging.getLogger(__name__).error("The voice agent cannot start: %s", setting_exception)
        raise SystemExit(1) from None
    uvicorn.run(
        app,
        host=host_settings.host,
        port=port,
        # "on" makes a failure while the app starts up stop the process; "auto" would log it and keep serving.
        lifespan="on",
        # The root handler above formats uvicorn's own lines too; uvicorn's default config would give them plain-text handlers.
        log_config=None,
    )


if __name__ == "__main__":
    main()
