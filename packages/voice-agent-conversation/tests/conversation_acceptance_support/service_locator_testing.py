from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, override

from conversation_acceptance_support.realtime_voice_service_scripted import RealtimeVoiceServiceScripted

from voice_agent_conversation import DomainFacade
from voice_agent_conversation.managers.configuration_providers.configuration_provider import ConfigurationProvider
from voice_agent_conversation.managers.service_locators.service_locator_base import ServiceLocatorBase
from voice_agent_restaurant import (
    ClockBase,
    ConfigurationProvider as RestaurantConfigurationProvider,
    DomainFacade as RestaurantDomainFacade,
    ServiceLocatorBase as RestaurantServiceLocatorBase,
)

RESTAURANT_DATABASE_PATH_VARIABLE_NAME: Final[str] = "VOICE_AGENT_RESTAURANT_DATABASE_PATH"
RESTAURANT_STORE_SEEDING_VARIABLE_NAME: Final[str] = "VOICE_AGENT_RESTAURANT_STORE_SEEDING"
OPENAI_API_KEY_VARIABLE_NAME: Final[str] = "OPENAI_API_KEY"
OPENAI_REALTIME_MODEL_VARIABLE_NAME: Final[str] = "VOICE_AGENT_OPENAI_REALTIME_MODEL"
OPENAI_REALTIME_WEBSOCKET_BASE_URL_VARIABLE_NAME: Final[str] = "VOICE_AGENT_OPENAI_REALTIME_WEBSOCKET_BASE_URL"
MAXIMUM_CALL_SECONDS_VARIABLE_NAME: Final[str] = "VOICE_AGENT_MAXIMUM_CALL_SECONDS"
MAXIMUM_SILENCE_SECONDS_VARIABLE_NAME: Final[str] = "VOICE_AGENT_MAXIMUM_SILENCE_SECONDS"
# A placeholder key: it only ever reaches the scripted Realtime service on this machine.
SCRIPTED_SERVICE_API_KEY: Final[str] = "scripted-realtime-service-key"
TESTING_REALTIME_MODEL: Final[str] = "gpt-realtime-testing"
# Wednesday 2026-11-04 at 15:00 in Riverton (America/Chicago, UTC-6).
WEDNESDAY_AFTERNOON_UTC: Final[datetime] = datetime(2026, 11, 4, 21, 0, tzinfo=UTC)


class ClockFixed(ClockBase):
    def __init__(self, fixed_now_utc: datetime) -> None:
        self._fixed_now_utc: datetime = fixed_now_utc

    @override
    def now_utc(self) -> datetime:
        return self._fixed_now_utc


class RestaurantServiceLocatorTesting(RestaurantServiceLocatorBase):
    # The restaurant runs for real on a temporary database; only its clock is fixed so "now" never moves.

    def __init__(self, restaurant_database_path: Path) -> None:
        self._restaurant_database_path: Path = restaurant_database_path

    @override
    def get_configuration_provider(self) -> RestaurantConfigurationProvider:
        return RestaurantConfigurationProvider(
            {
                RESTAURANT_DATABASE_PATH_VARIABLE_NAME: str(self._restaurant_database_path),
                RESTAURANT_STORE_SEEDING_VARIABLE_NAME: "restaurant_and_demo_bookings",
            }
        )

    @override
    def create_clock(self) -> ClockBase:
        return ClockFixed(WEDNESDAY_AFTERNOON_UTC)


class ServiceLocatorTesting(ServiceLocatorBase):
    # Nothing of the conversation domain is swapped. The real configuration provider points the real speech
    # gateway at the scripted Realtime service, so only the far end of the provider's wire differs.

    def __init__(self, override_by_environment_variable_name: Mapping[str, str], restaurant_database_path: Path) -> None:
        self._override_by_environment_variable_name: Mapping[str, str] = override_by_environment_variable_name
        self._restaurant_database_path: Path = restaurant_database_path

    @override
    def get_configuration_provider(self) -> ConfigurationProvider:
        return ConfigurationProvider(self._override_by_environment_variable_name)

    @override
    def create_restaurant_domain_facade(self) -> RestaurantDomainFacade:
        return create_restaurant_domain_facade(self._restaurant_database_path)


def create_domain_facade(
    realtime_voice_service_scripted: RealtimeVoiceServiceScripted,
    restaurant_database_path: Path,
    scenario_setting_by_environment_variable_name: Mapping[str, str] | None = None,
) -> DomainFacade:
    """The single place tests create the conversation DomainFacade. A scenario arranges settings such as call limits
    through scenario_setting_by_environment_variable_name; every other setting keeps its production default."""
    return DomainFacade(
        create_service_locator_testing(realtime_voice_service_scripted, restaurant_database_path, scenario_setting_by_environment_variable_name)
    )


def create_service_locator_testing(
    realtime_voice_service_scripted: RealtimeVoiceServiceScripted,
    restaurant_database_path: Path,
    scenario_setting_by_environment_variable_name: Mapping[str, str] | None = None,
) -> ServiceLocatorTesting:
    """The locator a test hands the DomainFacade itself, when constructing the facade is what the test exercises."""
    return ServiceLocatorTesting(
        {
            OPENAI_API_KEY_VARIABLE_NAME: SCRIPTED_SERVICE_API_KEY,
            OPENAI_REALTIME_MODEL_VARIABLE_NAME: TESTING_REALTIME_MODEL,
            OPENAI_REALTIME_WEBSOCKET_BASE_URL_VARIABLE_NAME: realtime_voice_service_scripted.websocket_base_url,
            **(scenario_setting_by_environment_variable_name or {}),
        },
        restaurant_database_path,
    )


def create_restaurant_domain_facade(restaurant_database_path: Path) -> RestaurantDomainFacade:
    # The restaurant behind the agent's briefing, which tests also read to arrange what the agent must be told.
    return RestaurantDomainFacade(RestaurantServiceLocatorTesting(restaurant_database_path))
