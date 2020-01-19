from libp2p.io.abc import ReadWriteCloser
from libp2p.io.exceptions import IOException

from .exceptions import RawConnError
from .raw_connection_interface import IRawConnection


class RawConnection(IRawConnection):
    stream: ReadWriteCloser
    is_initiator: bool

    def __init__(self, stream: ReadWriteCloser, initiator: bool) -> None:
        self.stream = stream
        self.is_initiator = initiator

    async def write(self, data: bytes) -> None:
        """Raise `RawConnError` if the underlying connection breaks."""
        try:
            await self.stream.write(data)
        except IOException as error:
            raise RawConnError(error)

    async def read(self, n: int = -1) -> bytes:
        """
        Read up to ``n`` bytes from the underlying stream. This call is
        delegated directly to the underlying ``self.reader``.

        Raise `RawConnError` if the underlying connection breaks
        """
        try:
            return await self.stream.read(n)
        except IOException as error:
            raise RawConnError(error)

    async def close(self) -> None:
        await self.stream.close()
