from abc import ABC, abstractmethod


class IPeerData(ABC):

    @abstractmethod
    def get_protocols(self):
        """
        :return: all protocols associated with given peer
        """

    @abstractmethod
    def add_protocols(self, protocols):
        """
        :param protocols: protocols to add
        """

    @abstractmethod
    def set_protocols(self, protocols):
        """
        :param protocols: protocols to add
        """

    @abstractmethod
    def add_addrs(self, addrs):
        """
        :param addrs: multiaddresses to add
        """

    @abstractmethod
    def get_addrs(self):
        """
        :return: all multiaddresses
        """

    @abstractmethod
    def clear_addrs(self):
        """
        Clear all addresses
        """

    @abstractmethod
    def put_metadata(self, key, val):
        """
        :param key: key in KV pair
        :param val: val to associate with key
        :raise Exception: unsuccesful put
        """

    @abstractmethod
    def get_metadata(self, key):
        """
        :param key: key in KV pair
        :return: val for key
        :raise Exception: key not found
        """
