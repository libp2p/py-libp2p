from abc import ABC, abstractmethod
from typing import Any, Tuple

from multiaddr import Multiaddr
import trio


class IListener(ABC):
    @abstractmethod
    async def listen(
        self, maddr: Multiaddr, task_status: Any = trio.TASK_STATUS_IGNORED
    ) -> bool:
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
