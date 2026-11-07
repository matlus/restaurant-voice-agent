from typing import final, override

from voice_agent_restaurant.managers.clocks.clock_base import ClockBase
from voice_agent_restaurant.managers.clocks.clock_system import ClockSystem
from voice_agent_restaurant.managers.configuration_providers.configuration_provider import ConfigurationProvider
from voice_agent_restaurant.managers.service_locators.service_locator_base import ServiceLocatorBase


@final
class ServiceLocatorProduction(ServiceLocatorBase):
    @override
    def get_configuration_provider(self) -> ConfigurationProvider:
        return ConfigurationProvider()

    @override
    def create_clock(self) -> ClockBase:
        return ClockSystem()
