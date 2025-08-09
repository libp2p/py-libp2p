from trio.abc import Stream
import trio

from libp2p.io.abc import ReadWriteCloser
from libp2p.io.exceptions import IOException


class P2PWebSocketConnection(ReadWriteCloser):
    """
    Wraps a WebSocketConnection to provide the raw stream interface
    that libp2p protocols expect.
    """

    def __init__(self, ws_connection, ws_context=None):
        self._ws_connection = ws_connection
        self._ws_context = ws_context
        self._read_buffer = b""
        self._read_lock = trio.Lock()

    async def write(self, data: bytes) -> None:
        try:
            # Send as a binary WebSocket message
            await self._ws_connection.send_message(data)
        except Exception as e:
            raise IOException from e

    async def read(self, n: int | None = None) -> bytes:
        """
        Read up to n bytes (if n is given), else read up to 64KiB.
        """
        async with self._read_lock:
            try:
                # If we have buffered data, return it
                if self._read_buffer:
                    if n is None:
                        result = self._read_buffer
                        self._read_buffer = b""
                        return result
                    else:
                        if len(self._read_buffer) >= n:
                            result = self._read_buffer[:n]
                            self._read_buffer = self._read_buffer[n:]
                            return result
                        else:
                            result = self._read_buffer
                            self._read_buffer = b""
                            return result

                # Get the next WebSocket message
                message = await self._ws_connection.get_message()
                if isinstance(message, str):
                    message = message.encode('utf-8')
                
                # Add to buffer
                self._read_buffer = message
                
                # Return requested amount
                if n is None:
                    result = self._read_buffer
                    self._read_buffer = b""
                    return result
                else:
                    if len(self._read_buffer) >= n:
                        result = self._read_buffer[:n]
                        self._read_buffer = self._read_buffer[n:]
                        return result
                    else:
                        result = self._read_buffer
                        self._read_buffer = b""
                        return result
                        
            except Exception as e:
                raise IOException from e

    async def close(self) -> None:
        # Close the WebSocket connection
        await self._ws_connection.aclose()
        # Exit the context manager if we have one
        if self._ws_context is not None:
            await self._ws_context.__aexit__(None, None, None)

    def get_remote_address(self) -> tuple[str, int] | None:
        # Try to get remote address from the WebSocket connection
        try:
            remote = self._ws_connection.remote
            if hasattr(remote, 'address') and hasattr(remote, 'port'):
                return str(remote.address), int(remote.port)
            elif isinstance(remote, str):
                # Parse address:port format
                if ':' in remote:
                    host, port = remote.rsplit(':', 1)
                    return host, int(port)
        except Exception:
            pass
        return None
