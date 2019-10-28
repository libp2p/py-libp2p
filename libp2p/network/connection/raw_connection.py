import asyncio

from .exceptions import RawConnError
from .raw_connection_interface import IRawConnection


class RawConnection(IRawConnection):
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    is_initiator: bool

    _drain_lock: asyncio.Lock

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        initiator: bool,
    ) -> None:
        self.reader = reader
        self.writer = writer
        self.is_initiator = initiator

        self._drain_lock = asyncio.Lock()

    async def write(self, data: bytes) -> None:
        """Raise `RawConnError` if the underlying connection breaks."""
        try:
            self.writer.write(data)
        except ConnectionResetError as error:
            raise RawConnError(error)
        # Reference: https://github.com/ethereum/lahja/blob/93610b2eb46969ff1797e0748c7ac2595e130aef/lahja/asyncio/endpoint.py#L99-L102  # noqa: E501
        # Use a lock to serialize drain() calls. Circumvents this bug:
        # https://bugs.python.org/issue29930
        async with self._drain_lock:
            try:
                await self.writer.drain()
            except ConnectionResetError as error:
                raise RawConnError(error)

    async def read(self, n: int = -1) -> bytes:
        """
        Read up to ``n`` bytes from the underlying stream. This call is
        delegated directly to the underlying ``self.reader``.

        Raise `RawConnError` if the underlying connection breaks
        """
        try:
            return await self.reader.read(n)
        except ConnectionResetError as error:
            raise RawConnError(error)

    async def close(self) -> None:
        self.writer.close()
        await self.writer.wait_closed()
