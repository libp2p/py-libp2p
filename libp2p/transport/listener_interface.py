from abc import (
    ABC,
    abstractmethod,
)

from multiaddr import (
    Multiaddr,
)
import trio


class IListener(ABC):
    @abstractmethod
    async def listen(self, maddr: Multiaddr, nursery: trio.Nursery) -> bool:
        """
        Put listener in listening mode and wait for incoming connections.

        :param maddr: multiaddr of peer
        :return: return True if successful
        """

    @abstractmethod
    def get_addrs(self) -> tuple[Multiaddr, ...]:
        """
        Retrieve list of addresses the listener is listening on.

        :return: return list of addrs
        """

    @abstractmethod
    async def close(self) -> None:
        ...
