import logging

import trio

from libp2p.io.abc import (
    ReadWriteCloser,
)

logger = logging.getLogger(__name__)


class TrioTCPStream(ReadWriteCloser):
    stream: trio.SocketStream
    # NOTE: Add both read and write lock to avoid `trio.BusyResourceError`
    read_lock: trio.Lock
    write_lock: trio.Lock
    # Cache remote address to avoid repeated lookups and handle cases where
    # socket becomes unavailable after connection establishment
    _cached_remote_address: tuple[str, int] | None

    def __init__(self, stream: trio.SocketStream) -> None:
        self.stream = stream
        self.read_lock = trio.Lock()
        self.write_lock = trio.Lock()
        self._cached_remote_address = None

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
        """
        Return the remote address as (host, port) tuple.

        This method caches the remote address on first successful retrieval
        to handle cases where the socket might become unavailable later
        (e.g., during connection teardown or in certain error states).

        Returns:
            A tuple of (host, port) or None if the address cannot be determined.

        """
        # Return cached value if available
        if self._cached_remote_address is not None:
            return self._cached_remote_address

        # Try to get remote address from socket
        try:
            # Check if socket attribute exists
            if not hasattr(self.stream, "socket"):
                logger.debug("SocketStream has no 'socket' attribute")
                return None

            socket = self.stream.socket
            if socket is None:
                logger.debug("Socket is None")
                return None

            # Attempt to get remote address
            remote_addr = socket.getpeername()

            # Validate the result
            if not isinstance(remote_addr, tuple) or len(remote_addr) != 2:
                logger.debug(f"Invalid remote address format: {remote_addr}")
                return None

            # Convert to (str, int) tuple as expected by the interface
            host, port = remote_addr
            result = (str(host), int(port))

            # Cache the result for future calls
            self._cached_remote_address = result
            return result

        except AttributeError as e:
            # Socket attribute doesn't exist or is not accessible
            logger.debug(
                "AttributeError getting remote address: %s (stream type: %s)",
                e,
                type(self.stream),
            )
            return None
        except OSError as e:
            # OSError can occur if:
            # - Socket is closed
            # - Socket is not connected
            # - Socket is in an invalid state
            # This is expected in some scenarios (e.g., connection teardown)
            logger.debug(
                "OSError getting remote address (socket may be closed/invalid): %s", e
            )
            return None
        except Exception as e:
            # Catch any other unexpected errors
            logger.warning(
                "Unexpected error getting remote address: %s (stream type: %s)",
                e,
                type(self.stream),
            )
            return None
