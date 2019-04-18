from abc import ABC, abstractmethod
# pylint: disable=too-few-public-methods


class IContentRouting(ABC):

    @abstractmethod
    def provide(self, cid, announce=True):
        """
        Provide adds the given cid to the content routing system. If announce is True,
        it also announces it, otherwise it is just kept in the local
        accounting of which objects are being provided.
        """

    @abstractmethod
    def find_provider_iter(self, cid, count):
        """
        Search for peers who are able to provide a given key
        returns an iterator of peer.PeerInfo
        """


class IPeerRouting(ABC):

    @abstractmethod
    def find_peer(self, peer_id):
        """
        Find specific Peer
        FindPeer searches for a peer with given peer_id, returns a peer.PeerInfo
        with relevant addresses.
        """
