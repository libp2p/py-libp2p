from abc import ABC, abstractmethod
from typing import Any

from .id import ID


class IPeerMetadata(ABC):
    def __init__(self) -> None:
        pass

    @abstractmethod
    def get(self, peer_id: ID, key: str) -> Any:
        """
        :param peer_id: peer ID to lookup key for
        :param key: key to look up
        :return: value at key for given peer
        :raise Exception: peer ID not found
        """

    @abstractmethod
    def put(self, peer_id: ID, key: str, val: Any) -> None:
        """
        :param peer_id: peer ID to lookup key for
        :param key: key to associate with peer
        :param val: value to associated with key
        :raise Exception: unsuccessful put
        """
