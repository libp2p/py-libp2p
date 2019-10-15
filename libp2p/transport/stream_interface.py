from abc import ABC, abstractmethod
from typing import Any


class IStream(ABC):
    """
    This is the common interface for both IStreamReader and IStreamWriter.
    In asyncio, just StreamWriter implements 'get_extra_info', however,
    it is more intuitive to be able to close it from any of them.

    This interface is not intended to be implemented directly by any class.
    """

    @abstractmethod
    def get_extra_info(self, field: str) -> Any:
        pass

    @abstractmethod
    async def close(self) -> None:
        pass


class IStreamReader(IStream):
    @abstractmethod
    async def read(self, n: int = -1) -> bytes:
        pass


class IStreamWriter(IStream):
    @abstractmethod
    async def write(self, data: bytes) -> None:
        pass
