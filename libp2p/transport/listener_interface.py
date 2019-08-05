from abc import ABC, abstractmethod
from typing import List

from multiaddr import Multiaddr


class IListener(ABC):
    @abstractmethod
    async def listen(self, maddr: Multiaddr) -> bool:
        """
        put listener in listening mode and wait for incoming connections
        :param maddr: multiaddr of peer
        :return: return True if successful
        """

    @abstractmethod
    def get_addrs(self) -> List[Multiaddr]:
        """
        retrieve list of addresses the listener is listening on
        :return: return list of addrs
        """

    @abstractmethod
    def close(self) -> bool:
        """
        close the listener such that no more connections
        can be open on this transport instance
        :return: return True if successful
        """
