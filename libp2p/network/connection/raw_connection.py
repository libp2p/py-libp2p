import asyncio
import sys

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
        # Detect if underlying transport is closing before write data to it
        # ref: https://github.com/ethereum/trinity/pull/614
        if self.writer.transport.is_closing():
            raise RawConnError("Transport is closing")
        self.writer.write(data)
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
        if self.writer.transport.is_closing():
            return
        self.writer.close()
        if sys.version_info < (3, 7):
            return
        try:
            await self.writer.wait_closed()
        # In case the connection is already reset.
        except ConnectionResetError:
            return
