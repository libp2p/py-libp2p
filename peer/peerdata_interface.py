from abc import ABC, abstractmethod

class IPeerData(ABC):

    """
    :return: all protocols associated with given peer
    """
    def get_protocols(self):
        pass

    """
    :param protocols: protocols to add
    """
    def add_protocols(self, protocols):
        pass

    """
    :param addrs: multiaddresses to add
    """
    def add_addrs(self, addrs):
        pass

    """
    :return: all multiaddresses
    """
    def get_addrs(self):
        pass

    """
    Clear all addresses
    """
    def clear_addrs(self):
        pass

    """
    :param key: key in KV pair
    :param val: val to associate with key
    """
    def put_metadata(self, key, val):
        pass

    """
    :param key: key in KV pair
    :return: val for key, error (only defined if key not found)
    """
    def get_metadata(self, key):
        pass
