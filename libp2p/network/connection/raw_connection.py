import asyncio

from libp2p.transport.stream_interface import IStreamReader, IStreamWriter

from .exceptions import RawConnError
from .raw_connection_interface import IRawConnection


class RawConnection(IRawConnection):
    reader: IStreamReader
    writer: IStreamWriter
    initiator: bool

    _drain_lock: asyncio.Lock

    def __init__(
        self, reader: IStreamReader, writer: IStreamWriter, initiator: bool
    ) -> None:
        self.reader = reader
        self.writer = writer
        self.initiator = initiator

        self._drain_lock = asyncio.Lock()

    async def write(self, data: bytes) -> None:
        """
        Raise `RawConnError` if the underlying connection breaks
        """
        # Reference: https://github.com/ethereum/lahja/blob/93610b2eb46969ff1797e0748c7ac2595e130aef/lahja/asyncio/endpoint.py#L99-L102  # noqa: E501
        # Use a lock to serialize drain() calls. Circumvents this bug:
        # https://bugs.python.org/issue29930
        async with self._drain_lock:
            try:
                await self.writer.write(
                    data
                )  # We call it inside the drain lock, because write() calls drain
            except ConnectionResetError as error:
                raise RawConnError(error)

    async def read(self, n: int = -1) -> bytes:
        """
        Read up to ``n`` bytes from the underlying stream.
        This call is delegated directly to the underlying ``self.reader``.

        Raise `RawConnError` if the underlying connection breaks
        """
        try:
            return await self.reader.read(n)
        except ConnectionResetError as error:
            raise RawConnError(error)

    async def close(self) -> None:
        await self.writer.close()
