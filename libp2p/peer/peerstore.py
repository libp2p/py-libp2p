from typing import Any, Dict, List, Optional, Sequence

from multiaddr import Multiaddr

from .id import ID
from .peerdata import PeerData
from .peerinfo import PeerInfo
from .peerstore_interface import IPeerStore


class PeerStore(IPeerStore):

    peer_map: Dict[ID, PeerData]

    def __init__(self) -> None:
        IPeerStore.__init__(self)
        self.peer_map = {}

    def __create_or_get_peer(self, peer_id: ID) -> PeerData:
        """
        Returns the peer data for peer_id or creates a new
        peer data (and stores it in peer_map) if peer
        data for peer_id does not yet exist
        :param peer_id: peer ID
        :return: peer data
        """
        if peer_id in self.peer_map:
            return self.peer_map[peer_id]
        data = PeerData()
        self.peer_map[peer_id] = data
        return self.peer_map[peer_id]

    def peer_info(self, peer_id: ID) -> Optional[PeerInfo]:
        if peer_id in self.peer_map:
            peer_data = self.peer_map[peer_id]
            return PeerInfo(peer_id, peer_data)
        return None

    def get_protocols(self, peer_id: ID) -> List[str]:
        if peer_id in self.peer_map:
            return self.peer_map[peer_id].get_protocols()
        raise PeerStoreError("peer ID not found")

    def add_protocols(self, peer_id: ID, protocols: Sequence[str]) -> None:
        peer = self.__create_or_get_peer(peer_id)
        peer.add_protocols(list(protocols))

    def set_protocols(self, peer_id: ID, protocols: Sequence[str]) -> None:
        peer = self.__create_or_get_peer(peer_id)
        peer.set_protocols(list(protocols))

    def peer_ids(self) -> List[ID]:
        return list(self.peer_map.keys())

    def get(self, peer_id: ID, key: str) -> Any:
        if peer_id in self.peer_map:
            val = self.peer_map[peer_id].get_metadata(key)
            return val
        raise PeerStoreError("peer ID not found")

    def put(self, peer_id: ID, key: str, val: Any) -> None:
        # <<?>>
        # This can output an error, not sure what the possible errors are
        peer = self.__create_or_get_peer(peer_id)
        peer.put_metadata(key, val)

    def add_addr(self, peer_id: ID, addr: Multiaddr, ttl: int) -> None:
        self.add_addrs(peer_id, [addr], ttl)

    def add_addrs(self, peer_id: ID, addrs: Sequence[Multiaddr], ttl: int) -> None:
        # Ignore ttl for now
        peer = self.__create_or_get_peer(peer_id)
        peer.add_addrs(list(addrs))

    def addrs(self, peer_id: ID) -> List[Multiaddr]:
        if peer_id in self.peer_map:
            return self.peer_map[peer_id].get_addrs()
        raise PeerStoreError("peer ID not found")

    def clear_addrs(self, peer_id: ID) -> None:
        # Only clear addresses if the peer is in peer map
        if peer_id in self.peer_map:
            self.peer_map[peer_id].clear_addrs()

    def peers_with_addrs(self) -> List[ID]:
        # Add all peers with addrs at least 1 to output
        output: List[ID] = []

        for peer_id in self.peer_map:
            if len(self.peer_map[peer_id].get_addrs()) >= 1:
                output.append(peer_id)
        return output


class PeerStoreError(KeyError):
    """Raised when peer ID is not found in peer store"""
