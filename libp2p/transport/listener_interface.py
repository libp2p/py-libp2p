from abc import ABC, abstractmethod


class IListener(ABC):

    @abstractmethod
    def listen(self, maddr):
        """
        put listener in listening mode and wait for incoming connections
        :param maddr: multiaddr of peer
        :return: return True if successful
        """

    @abstractmethod
    def get_addrs(self):
        """
        retrieve list of addresses the listener is listening on
        :return: return list of addrs
        """

    @abstractmethod
    def close(self, options=None):
        """
        close the listener such that no more connections
        can be open on this transport instance
        :param options: optional object potential with timeout
        a timeout value in ms that fires and destroy all connections
        :return: return True if successful
        """
