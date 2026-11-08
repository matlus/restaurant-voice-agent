from abc import ABC, abstractmethod

from voice_agent_conversation.managers.configuration_providers.configuration_provider import ConfigurationProvider
from voice_agent_restaurant import DomainFacade as RestaurantDomainFacade


class ServiceLocatorBase(ABC):
    """Creates the components tests must swap. Accessible only to the domain facade and managers.

    The speech gateway is not here: the manager creates the real one, and tests point it at a scripted
    Realtime service through configuration, so the gateway's own code runs in every test.
    """

    @abstractmethod
    def get_configuration_provider(self) -> ConfigurationProvider: ...

    @abstractmethod
    def create_restaurant_domain_facade(self) -> RestaurantDomainFacade: ...
