from typing import final, override

from voice_agent_conversation.managers.configuration_providers.configuration_provider import ConfigurationProvider
from voice_agent_conversation.managers.service_locators.service_locator_base import ServiceLocatorBase
from voice_agent_restaurant import DomainFacade as RestaurantDomainFacade


@final
class ServiceLocatorProduction(ServiceLocatorBase):
    @override
    def get_configuration_provider(self) -> ConfigurationProvider:
        return ConfigurationProvider()

    @override
    def create_restaurant_domain_facade(self) -> RestaurantDomainFacade:
        return RestaurantDomainFacade()
