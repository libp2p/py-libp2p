from typing import Any, Dict, List, Optional, Sequence, Set

from multiaddr import Multiaddr

from libp2p.crypto.keys import KeyPair, PrivateKey, PublicKey

from .id import ID
from .peerdata import PeerData, PeerDataError
from .peerinfo import PeerInfo
from .peerstore_interface import IPeerStore


class PeerStore(IPeerStore):

    peer_pubkey_map: Dict[ID, PublicKey]
    peer_privkey_map: Dict[ID, PrivateKey]
    peer_data_map: Dict[ID, PeerData]

    def __init__(self) -> None:
        self.peer_pubkey_map = {}
        self.peer_privkey_map = {}
        self.peer_data_map = {}

    def __create_or_get_peer(self, peer_id: ID) -> PeerData:
        """
        Returns the peer data for peer_id or creates a new peer data (and
        stores it in peer_data_map) if peer data for peer_id does not yet
        exist.

        :param peer_id: peer ID
        :return: peer data
        """
        if peer_id in self.peer_data_map:
            return self.peer_data_map[peer_id]
        data = PeerData()
        self.peer_data_map[peer_id] = data
        return data

    def peer_info(self, peer_id: ID) -> Optional[PeerInfo]:
        """
        :param peer_id: peer ID to get info for
        :return: peer info object
        """
        if peer_id in self.peer_data_map:
            peer_data = self.peer_data_map[peer_id]
            return PeerInfo(peer_id, peer_data.addrs)
        return None

    def get_protocols(self, peer_id: ID) -> List[str]:
        """
        :param peer_id: peer ID to get protocols for
        :return: protocols (as list of strings)
        :raise PeerStoreError: if peer ID not found
        """
        if peer_id in self.peer_data_map:
            return self.peer_data_map[peer_id].get_protocols()
        raise PeerStoreError("peer ID not found")

    def add_protocols(self, peer_id: ID, protocols: Sequence[str]) -> None:
        """
        :param peer_id: peer ID to add protocols for
        :param protocols: protocols to add
        """
        peer = self.__create_or_get_peer(peer_id)
        peer.add_protocols(list(protocols))

    def set_protocols(self, peer_id: ID, protocols: Sequence[str]) -> None:
        """
        :param peer_id: peer ID to set protocols for
        :param protocols: protocols to set
        """
        peer = self.__create_or_get_peer(peer_id)
        peer.set_protocols(list(protocols))

    def peer_ids(self) -> List[ID]:
        """
        :return: all of the peer IDs stored in peer store
        """
        return list(self.peer_data_map.keys())

    def get(self, peer_id: ID, key: str) -> Any:
        """
        :param peer_id: peer ID to get peer data for
        :param key: the key to search value for
        :return: value corresponding to the key
        :raise PeerStoreError: if peer ID or value not found
        """
        if peer_id in self.peer_data_map:
            try:
                val = self.peer_data_map[peer_id].get_metadata(key)
            except PeerDataError as error:
                raise PeerStoreError(error)
            return val
        raise PeerStoreError("peer ID not found")

    def put(self, peer_id: ID, key: str, val: Any) -> None:
        """
        :param peer_id: peer ID to put peer data for
        :param key:
        :param value:
        """
        # <<?>>
        # This can output an error, not sure what the possible errors are
        peer = self.__create_or_get_peer(peer_id)
        peer.put_metadata(key, val)

    def add_addr(self, peer_id: ID, addr: Multiaddr, ttl: int) -> None:
        """
        :param peer_id: peer ID to add address for
        :param addr:
        :param ttl: time-to-live for the this record
        """
        self.add_addrs(peer_id, [addr], ttl)

    def add_addrs(self, peer_id: ID, addrs: Sequence[Multiaddr], ttl: int) -> None:
        """
        :param peer_id: peer ID to add address for
        :param addrs:
        :param ttl: time-to-live for the this record
        """
        # Ignore ttl for now
        peer = self.__create_or_get_peer(peer_id)
        peer.add_addrs(list(addrs))

    def addrs(self, peer_id: ID) -> List[Multiaddr]:
        """
        :param peer_id: peer ID to get addrs for
        :return: list of addrs
        :raise PeerStoreError: if peer ID not found
        """
        if peer_id in self.peer_data_map:
            return self.peer_data_map[peer_id].get_addrs()
        raise PeerStoreError("peer ID not found")

    def clear_addrs(self, peer_id: ID) -> None:
        """
        :param peer_id: peer ID to clear addrs for
        """
        # Only clear addresses if the peer is in peer map
        if peer_id in self.peer_data_map:
            self.peer_data_map[peer_id].clear_addrs()

    def peers_with_addrs(self) -> List[ID]:
        """
        :return: all of the peer IDs which has addrs stored in peer store
        """
        # Add all peers with addrs at least 1 to output
        output: List[ID] = []

        for peer_id in self.peer_data_map:
            if len(self.peer_data_map[peer_id].get_addrs()) >= 1:
                output.append(peer_id)
        return output

    def add_pubkey(self, peer_id: ID, pubkey: PublicKey) -> None:
        """
        :param peer_id: peer ID to add public key for
        :param pubkey:
        :raise PeerStoreError: if peer ID already has pubkey set
        """
        if peer_id in self.peer_pubkey_map:
            raise PeerStoreError(
                f"peer ID already has pubkey: {self.peer_pubkey_map[peer_id]}"
            )
        self.peer_pubkey_map[peer_id] = pubkey

    def pubkey(self, peer_id: ID) -> PublicKey:
        """
        :param peer_id: peer ID to get public key for
        :return: public key of the peer
        :raise PeerStoreError: if peer ID not found
        """
        if peer_id in self.peer_pubkey_map:
            return self.peer_pubkey_map[peer_id]
        raise PeerStoreError("peer ID not found")

    def add_privkey(self, peer_id: ID, privkey: PrivateKey) -> None:
        """
        :param peer_id: peer ID to add private key for
        :param privkey:
        :raise PeerStoreError: if peer ID already has privkey set
        """
        if peer_id in self.peer_privkey_map:
            raise PeerStoreError(
                f"peer ID already has privkey: {self.peer_privkey_map[peer_id]}"
            )
        self.peer_privkey_map[peer_id] = privkey

    def privkey(self, peer_id: ID) -> PrivateKey:
        """
        :param peer_id: peer ID to get private key for
        :return: private key of the peer
        :raise PeerStoreError: if peer ID not found
        """
        if peer_id in self.peer_pubkey_map:
            return self.peer_privkey_map[peer_id]
        raise PeerStoreError("peer ID not found")

    def add_key_pair(self, peer_id: ID, key_pair: KeyPair) -> None:
        """
        :param peer_id: peer ID to add private key for
        :param key_pair:
        :raise PeerStoreError: if peer ID already has pubkey or privkey set
        """
        self.add_pubkey(peer_id, key_pair.public_keypubkey)
        self.add_privkey(peer_id, key_pair.private_key)

    def peers_with_keys(self) -> Set[ID]:
        """
        :return: all of the peer IDs which has pubkey/privkey stored in peer store
        """
        return set(self.peer_pubkey_map.keys()).union(self.peer_privkey_map.keys())


class PeerStoreError(KeyError):
    """Raised when peer ID is not found in peer store."""
