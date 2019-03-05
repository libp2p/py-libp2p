from abc import ABC, abstractmethod


class IPeerMetadata(ABC):

    def __init__(self):
        pass

    @abstractmethod
    def get(self, peer_id, key):
        """
        :param peer_id: peer ID to lookup key for
        :param key: key to look up
        :return: value at key for given peer
        :raise Exception: peer ID not found
        """

    @abstractmethod
    def put(self, peer_id, key, val):
        """
        :param peer_id: peer ID to lookup key for
        :param key: key to associate with peer
        :param val: value to associated with key
        :raise Exception: unsuccessful put
        """
