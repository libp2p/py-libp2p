import asyncio

from .raw_connection_interface import IRawConnection


class RawConnection(IRawConnection):
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    initiator: bool

    _drain_lock: asyncio.Lock

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        initiator: bool,
    ) -> None:
        self.reader = reader
        self.writer = writer
        self.initiator = initiator

        self._drain_lock = asyncio.Lock()

    async def write(self, data: bytes) -> None:
        self.writer.write(data)
        # Reference: https://github.com/ethereum/lahja/blob/93610b2eb46969ff1797e0748c7ac2595e130aef/lahja/asyncio/endpoint.py#L99-L102  # noqa: E501
        # Use a lock to serialize drain() calls. Circumvents this bug:
        # https://bugs.python.org/issue29930
        async with self._drain_lock:
            await self.writer.drain()

    async def read(self, n: int = -1) -> bytes:
        """
        Read up to ``n`` bytes from the underlying stream.
        This call is delegated directly to the underlying ``self.reader``.
        """
        return await self.reader.read(n)

    async def close(self) -> None:
        self.writer.close()
        await self.writer.wait_closed()
