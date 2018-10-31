from abc import ABC, abstractmethod

class IConnection(ABC):

    @abstractmethod
    def get_observed_addrs(self):
        """
        retrieve observed addresses from underlying transport
        :return: list of multiaddrs
        """
        pass

    @abstractmethod
    def get_peer_info(self):
        """
        retrieve peer info object that the connection connects to
        :return: a peer info object
        """
        pass

    @abstractmethod
    def set_peer_info(self, peer_info):
        """
        :param peer_info: a peer info object that contains info of peer
        :return: True if successful
        """
        pass
