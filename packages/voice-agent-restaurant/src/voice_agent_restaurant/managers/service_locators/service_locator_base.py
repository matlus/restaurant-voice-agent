from abc import ABC, abstractmethod

from voice_agent_restaurant.managers.clocks.clock_base import ClockBase
from voice_agent_restaurant.managers.configuration_providers.configuration_provider import ConfigurationProvider


class ServiceLocatorBase(ABC):
    """Creates the components tests must swap. Accessible only to the domain facade and managers.

    The store is not here: data managers open their own SQLite connections, and tests point
    them at a temporary database through configuration instead.
    """

    @abstractmethod
    def get_configuration_provider(self) -> ConfigurationProvider: ...

    @abstractmethod
    def create_clock(self) -> ClockBase: ...
