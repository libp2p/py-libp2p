from abc import ABC, abstractmethod
import asyncio

class IRawConnection(ABC):

    @abstractmethod
    def __init__(self, ip, port):
        pass

    @abstractmethod
    async def open_connection(self):
        pass
        