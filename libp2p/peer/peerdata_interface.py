from abc import ABC, abstractmethod
from typing import Any, List, Sequence

from multiaddr import Multiaddr

from libp2p.crypto.keys import PrivateKey, PublicKey

from .peermetadata_interface import IPeerMetadata


class IPeerData(ABC):
    @abstractmethod
    def get_protocols(self) -> List[str]:
        """
        :return: all protocols associated with given peer
        """

    @abstractmethod
    def add_protocols(self, protocols: Sequence[str]) -> None:
        """
        :param protocols: protocols to add
        """

    @abstractmethod
    def set_protocols(self, protocols: Sequence[str]) -> None:
        """
        :param protocols: protocols to set
        """

    @abstractmethod
    def add_addrs(self, addrs: Sequence[Multiaddr]) -> None:
        """
        :param addrs: multiaddresses to add
        """

    @abstractmethod
    def get_addrs(self) -> List[Multiaddr]:
        """
        :return: all multiaddresses
        """

    @abstractmethod
    def clear_addrs(self) -> None:
        """Clear all addresses."""

    @abstractmethod
    def put_metadata(self, key: str, val: Any) -> None:
        """
        :param key: key in KV pair
        :param val: val to associate with key
        """

    @abstractmethod
    def get_metadata(self, key: str) -> IPeerMetadata:
        """
        :param key: key in KV pair
        :return: val for key
        :raise PeerDataError: key not found
        """

    @abstractmethod
    def add_pubkey(self, pubkey: PublicKey) -> None:
        """
        :param pubkey:
        """

    @abstractmethod
    def get_pubkey(self) -> PublicKey:
        """
        :return: public key of the peer
        :raise PeerDataError: if public key not found
        """

    @abstractmethod
    def add_privkey(self, privkey: PrivateKey) -> None:
        """
        :param privkey:
        """

    @abstractmethod
    def get_privkey(self) -> PrivateKey:
        """
        :return: private key of the peer
        :raise PeerDataError: if private key not found
        """
