import trio
from trio import SocketStream
from libp2p.io.abc import ReadWriteCloser
from libp2p.io.exceptions import IOException
import logging


logger = logging.getLogger("libp2p.io.trio")


class TrioReadWriteCloser(ReadWriteCloser):
    stream: SocketStream

    def __init__(self, stream: SocketStream) -> None:
        self.stream = stream

    async def write(self, data: bytes) -> None:
        """Raise `RawConnError` if the underlying connection breaks."""
        try:
            await self.stream.send_all(data)
        except (trio.ClosedResourceError, trio.BrokenResourceError) as error:
            raise IOException(error)

    async def read(self, n: int = -1) -> bytes:
        max_bytes = n if n != -1 else None
        try:
            return await self.stream.receive_some(max_bytes)
        except (trio.ClosedResourceError, trio.BrokenResourceError) as error:
            raise IOException(error)

    async def close(self) -> None:
        await self.stream.aclose()
