from abc import abstractmethod

from .addrbook_interface import IAddrBook
from .peermetadata_interface import IPeerMetadata


class IPeerStore(IAddrBook, IPeerMetadata):

    def __init__(self):
        IPeerMetadata.__init__(self)
        IAddrBook.__init__(self)

    @abstractmethod
    def peer_info(self, peer_id):
        """
        :param peer_id: peer ID to get info for
        :return: peer info object
        """

    @abstractmethod
    def get_protocols(self, peer_id):
        """
        :param peer_id: peer ID to get protocols for
        :return: protocols (as strings)
        :raise Exception: peer ID not found exception
        """

    @abstractmethod
    def add_protocols(self, peer_id, protocols):
        """
        :param peer_id: peer ID to add protocols for
        :param protocols: protocols to add
        :raise Exception: peer ID not found
        """

    @abstractmethod
    def set_protocols(self, peer_id, protocols):
        """
        :param peer_id: peer ID to set protocols for
        :param protocols: protocols to set
        :raise Exception: peer ID not found
        """

    @abstractmethod
    def peers(self):
        """
        :return: all of the peer IDs stored in peer store
        """
