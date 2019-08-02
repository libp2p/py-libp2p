from abc import ABC, abstractmethod
from typing import Iterable

from libp2p.peer.id import ID
from libp2p.peer.peerinfo import PeerInfo


class IContentRouting(ABC):
    @abstractmethod
    def provide(self, cid: bytes, announce: bool = True) -> None:
        """
        Provide adds the given cid to the content routing system. If announce is True,
        it also announces it, otherwise it is just kept in the local
        accounting of which objects are being provided.
        """

    @abstractmethod
    def find_provider_iter(self, cid: bytes, count: int) -> Iterable[PeerInfo]:
        """
        Search for peers who are able to provide a given key
        returns an iterator of peer.PeerInfo
        """


class IPeerRouting(ABC):
    @abstractmethod
    async def find_peer(self, peer_id: ID) -> PeerInfo:
        """
        Find specific Peer
        FindPeer searches for a peer with given peer_id, returns a peer.PeerInfo
        with relevant addresses.
        """
