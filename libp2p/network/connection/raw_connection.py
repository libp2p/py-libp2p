from libp2p.abc import (
    IRawConnection,
)
from libp2p.io.abc import (
    ReadWriteCloser,
)
from libp2p.io.exceptions import (
    IOException,
)

from .exceptions import (
    RawConnError,
)


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
            raise RawConnError from error

    async def read(self, n: int | None = None) -> bytes:
        """
        Read up to ``n`` bytes from the underlying stream. This call is
        delegated directly to the underlying ``self.reader``.

        Raise `RawConnError` if the underlying connection breaks
        """
        try:
            return await self.stream.read(n)
        except IOException as error:
            raise RawConnError from error

    async def close(self) -> None:
        await self.stream.close()

    def get_remote_address(self) -> tuple[str, int] | None:
        """Delegate to the underlying stream's get_remote_address method."""
        return self.stream.get_remote_address()
