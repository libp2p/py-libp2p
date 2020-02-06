from abc import ABC, abstractmethod
from typing import Tuple

from multiaddr import Multiaddr
import trio


class IListener(ABC):
    @abstractmethod
    async def listen(self, maddr: Multiaddr, nursery: trio.Nursery) -> bool:
        """
        put listener in listening mode and wait for incoming connections.

        :param maddr: multiaddr of peer
        :return: return True if successful
        """

    @abstractmethod
    def get_addrs(self) -> Tuple[Multiaddr, ...]:
        """
        retrieve list of addresses the listener is listening on.

        :return: return list of addrs
        """

    @abstractmethod
    async def close(self) -> None:
        ...
