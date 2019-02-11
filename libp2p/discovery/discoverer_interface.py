from abc import ABC, abstractmethod
# pylint: disable=too-few-public-methods


class IDiscoverer(ABC):

    def __init__(self):
        pass

    @abstractmethod
    def find_peers(self, service):
        """
        Find peers on the networking providing a particular service
        :param service: service that peers must provide
        :return: peerstore containing found peers on the network
        :raise Exception: network error
        """
