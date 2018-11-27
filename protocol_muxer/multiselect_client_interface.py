from abc import ABC, abstractmethod
import asyncio

class IMultiselectClient(ABC):

    @abstractmethod
    async def select_proto_or_fail(self, protocol, stream):
        pass

    @abstractmethod
    async def select_one_of(self, protocols, stream):
        pass

    @abstractmethod
    async def try_select(self, protocol, stream):
        pass

    @abstractmethod
    async def handshake(self, stream):
        pass
