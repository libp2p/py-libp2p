import logging

import trio

from libp2p.io.abc import ReadWriteCloser
from libp2p.io.exceptions import IOException

logger = logging.getLogger("libp2p.io.trio")


class TrioTCPStream(ReadWriteCloser):
    stream: trio.SocketStream
    # NOTE: Add both read and write lock to avoid `trio.BusyResourceError`
    read_lock: trio.Lock
    write_lock: trio.Lock

    def __init__(self, stream: trio.SocketStream) -> None:
        self.stream = stream
        self.read_lock = trio.Lock()
        self.write_lock = trio.Lock()

    async def write(self, data: bytes) -> None:
        """Raise `RawConnError` if the underlying connection breaks."""
        async with self.write_lock:
            try:
                await self.stream.send_all(data)
            except (trio.ClosedResourceError, trio.BrokenResourceError) as error:
                raise IOException from error
            except trio.BusyResourceError as error:
                # This should never happen, since we already access streams with read/write locks.
                raise Exception(
                    "this should never happen "
                    "since we already access streams with read/write locks."
                ) from error

    async def read(self, n: int = -1) -> bytes:
        async with self.read_lock:
            if n == 0:
                # Checkpoint
                await trio.hazmat.checkpoint()
                return b""
            max_bytes = n if n != -1 else None
            try:
                return await self.stream.receive_some(max_bytes)
            except (trio.ClosedResourceError, trio.BrokenResourceError) as error:
                raise IOException from error
            except trio.BusyResourceError as error:
                # This should never happen, since we already access streams with read/write locks.
                raise Exception(
                    "this should never happen "
                    "since we already access streams with read/write locks."
                ) from error

    async def close(self) -> None:
        await self.stream.aclose()
