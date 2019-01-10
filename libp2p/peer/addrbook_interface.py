from abc import ABC, abstractmethod


class IAddrBook(ABC):

    def __init__(self):
        pass

    @abstractmethod
    def add_addr(self, peer_id, addr, ttl):
        """
        Calls add_addrs(peer_id, [addr], ttl)
        :param peer_id: the peer to add address for
        :param addr: multiaddress of the peer
        :param ttl: time-to-live for the address (after this time, address is no longer valid)
        """

    @abstractmethod
    def add_addrs(self, peer_id, addrs, ttl):
        """
        Adds addresses for a given peer all with the same time-to-live. If one of the
        addresses already exists for the peer and has a longer TTL, no operation should take place.
        If one of the addresses exists with a shorter TTL, extend the TTL to equal param ttl.
        :param peer_id: the peer to add address for
        :param addr: multiaddresses of the peer
        :param ttl: time-to-live for the address (after this time, address is no longer valid
        """

    @abstractmethod
    def addrs(self, peer_id):
        """
        :param peer_id: peer to get addresses of
        :return: all known (and valid) addresses for the given peer
        """

    @abstractmethod
    def clear_addrs(self, peer_id):
        """
        Removes all previously stored addresses
        :param peer_id: peer to remove addresses of
        """

    @abstractmethod
    def peers_with_addrs(self):
        """
        :return: all of the peer IDs stored with addresses
        """
