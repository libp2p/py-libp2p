import asyncio
from abc import ABC, abstractmethod


class IRawConnection(ABC):
    """
    A Raw Connection provides a Reader and a Writer
    """

    initiator: bool

    # TODO: reader and writer shouldn't be exposed.
    # Need better API for the consumers
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter

    @abstractmethod
    async def write(self, data: bytes) -> None:
        pass

    @abstractmethod
    async def read(self) -> bytes:
        pass

    @abstractmethod
    def close(self) -> None:
        pass

    @abstractmethod
    def next_stream_id(self) -> int:
        pass
