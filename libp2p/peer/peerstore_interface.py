from abc import abstractmethod
from typing import Any, List, Sequence

from multiaddr import Multiaddr

from libp2p.crypto.keys import KeyPair, PrivateKey, PublicKey

from .addrbook_interface import IAddrBook
from .id import ID
from .peerinfo import PeerInfo
from .peermetadata_interface import IPeerMetadata


class IPeerStore(IAddrBook, IPeerMetadata):
    @abstractmethod
    def peer_info(self, peer_id: ID) -> PeerInfo:
        """
        :param peer_id: peer ID to get info for
        :return: peer info object
        """

    @abstractmethod
    def get_protocols(self, peer_id: ID) -> List[str]:
        """
        :param peer_id: peer ID to get protocols for
        :return: protocols (as list of strings)
        :raise PeerStoreError: if peer ID not found
        """

    @abstractmethod
    def add_protocols(self, peer_id: ID, protocols: Sequence[str]) -> None:
        """
        :param peer_id: peer ID to add protocols for
        :param protocols: protocols to add
        """

    @abstractmethod
    def set_protocols(self, peer_id: ID, protocols: Sequence[str]) -> None:
        """
        :param peer_id: peer ID to set protocols for
        :param protocols: protocols to set
        """

    @abstractmethod
    def peer_ids(self) -> List[ID]:
        """
        :return: all of the peer IDs stored in peer store
        """

    @abstractmethod
    def get(self, peer_id: ID, key: str) -> Any:
        """
        :param peer_id: peer ID to get peer data for
        :param key: the key to search value for
        :return: value corresponding to the key
        :raise PeerStoreError: if peer ID or value not found
        """

    @abstractmethod
    def put(self, peer_id: ID, key: str, val: Any) -> None:
        """
        :param peer_id: peer ID to put peer data for
        :param key:
        :param value:
        """

    @abstractmethod
    def add_addr(self, peer_id: ID, addr: Multiaddr, ttl: int) -> None:
        """
        :param peer_id: peer ID to add address for
        :param addr:
        :param ttl: time-to-live for the this record
        """

    @abstractmethod
    def add_addrs(self, peer_id: ID, addrs: Sequence[Multiaddr], ttl: int) -> None:
        """
        :param peer_id: peer ID to add address for
        :param addrs:
        :param ttl: time-to-live for the this record
        """

    @abstractmethod
    def addrs(self, peer_id: ID) -> List[Multiaddr]:
        """
        :param peer_id: peer ID to get addrs for
        :return: list of addrs
        """

    @abstractmethod
    def clear_addrs(self, peer_id: ID) -> None:
        """
        :param peer_id: peer ID to clear addrs for
        """

    @abstractmethod
    def peers_with_addrs(self) -> List[ID]:
        """
        :return: all of the peer IDs which has addrs stored in peer store
        """

    @abstractmethod
    def add_pubkey(self, peer_id: ID, pubkey: PublicKey) -> None:
        """
        :param peer_id: peer ID to add public key for
        :param pubkey:
        :raise PeerStoreError: if peer ID already has pubkey set
        """

    @abstractmethod
    def pubkey(self, peer_id: ID) -> PublicKey:
        """
        :param peer_id: peer ID to get public key for
        :return: public key of the peer
        :raise PeerStoreError: if peer ID not found
        """

    @abstractmethod
    def add_privkey(self, peer_id: ID, privkey: PrivateKey) -> None:
        """
        :param peer_id: peer ID to add private key for
        :param privkey:
        :raise PeerStoreError: if peer ID already has privkey set
        """

    @abstractmethod
    def privkey(self, peer_id: ID) -> PrivateKey:
        """
        :param peer_id: peer ID to get private key for
        :return: private key of the peer
        :raise PeerStoreError: if peer ID not found
        """

    @abstractmethod
    def add_key_pair(self, peer_id: ID, key_pair: KeyPair) -> None:
        """
        :param peer_id: peer ID to add private key for
        :param key_pair:
        :raise PeerStoreError: if peer ID already has pubkey or privkey set
        """
