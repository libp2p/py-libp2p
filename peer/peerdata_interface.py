from abc import ABC, abstractmethod

class IPeerData(ABC):

    @abstractmethod
    def get_protocols(self):
        """
        :return: all protocols associated with given peer
        """
        pass

    @abstractmethod
    def add_protocols(self, protocols):
        """
        :param protocols: protocols to add
        """
        pass

    @abstractmethod
    def set_protocols(self, protocols):
        """
        :param protocols: protocols to add
        """
        pass

    @abstractmethod
    def add_addrs(self, addrs):
        """
        :param addrs: multiaddresses to add
        """
        pass

    @abstractmethod
    def get_addrs(self):
        """
        :return: all multiaddresses
        """
        pass

    @abstractmethod
    def clear_addrs(self):
        """
        Clear all addresses
        """
        pass

    @abstractmethod
    def put_metadata(self, key, val):
        """
        :param key: key in KV pair
        :param val: val to associate with key
        :raise Exception: unsuccesful put
        """
        pass

    @abstractmethod
    def get_metadata(self, key):
        """
        :param key: key in KV pair
        :return: val for key
        :raise Exception: key not found
        """
        pass
