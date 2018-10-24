from abc import ABC, abstractmethod
from .addrbook_interface import IAddrBook
from .peermetadata_interface import IPeerMetadata

class IPeerStore(ABC, IAddrBook, IPeerMetadata):

    def __init__(self, context):
        IPeerMetadata.__init__(self, context)
        IAddrBook.__init__(self, context)

    @abstractmethod
    def peer_info(self, peer_id):
        """
        :param peer_id: peer ID to get info for
        :return: peer info object
        """
        pass

    @abstractmethod
    def get_protocols(self, peer_id):
        """
        :param peer_id: peer ID to get protocols for
        :return: protocols (as strings), error
        """
        pass

    @abstractmethod
    def add_protocols(self, peer_id, protocols):
        """
        :param peer_id: peer ID to add protocols for
        :param protocols: protocols to add
        :return: error
        """
        pass

    @abstractmethod
    def set_protocols(self, peer_id, protocols):
        """
        :param peer_id: peer ID to set protocols for
        :param protocols: protocols to set
        :return: error
        """
        pass

    @abstractmethod
    def peers(self):
        """
        :return: all of the peer IDs stored in peer store
        """
        pass
