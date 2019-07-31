from abc import ABC, abstractmethod
from typing import Any, List, Sequence

from multiaddr import Multiaddr

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
        :param protocols: protocols to add
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
        """
        Clear all addresses
        """

    @abstractmethod
    def put_metadata(self, key: str, val: Any) -> None:
        """
        :param key: key in KV pair
        :param val: val to associate with key
        :raise Exception: unsuccesful put
        """

    @abstractmethod
    def get_metadata(self, key: str) -> IPeerMetadata:
        """
        :param key: key in KV pair
        :return: val for key
        :raise Exception: key not found
        """
