from abc import ABC, abstractmethod

class IDiscoverer(ABC):

    def __init__(self):
        pass

    @abstractmethod
    def advertise(self, service):
        """
        Advertise providing a specific service to the network
        :param service: service that you provide
        :raise Exception: network error
        """