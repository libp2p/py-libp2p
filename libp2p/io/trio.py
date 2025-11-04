import logging

import trio

from libp2p.io.abc import (
    ReadWriteCloser,
)

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
        """Handle write operations gracefully when resources are closed."""
        async with self.write_lock:
            try:
                await self.stream.send_all(data)
            except (trio.ClosedResourceError, trio.BrokenResourceError) as error:
                # Underlying socket is closed or broken — treat as normal closure
                # during peer disconnection scenarios rather than raising an error
                logger.debug("Write attempted on closed/broken resource: %s", error)
                # Don't raise IOException - treat as successful write to closed stream
                return

    async def read(self, n: int | None = None) -> bytes:
        async with self.read_lock:
            if n is not None and n == 0:
                return b""
            try:
                return await self.stream.receive_some(n)
            except (trio.ClosedResourceError, trio.BrokenResourceError) as error:
                # Underlying socket is closed/broken. Return empty bytes to
                # indicate EOF/closure and allow higher layers to handle removal
                # without raising additional exceptions during their cleanup.
                logger.debug("Read attempted on closed/broken resource: %s", error)
                return b""

    async def close(self) -> None:
        await self.stream.aclose()

    def get_remote_address(self) -> tuple[str, int] | None:
        """Return the remote address as (host, port) tuple."""
        try:
            return self.stream.socket.getpeername()
        except (AttributeError, OSError) as e:
            logger.error("Error getting remote address: %s", e)
            return None
