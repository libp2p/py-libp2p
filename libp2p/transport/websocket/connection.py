from trio.abc import Stream

from libp2p.io.abc import ReadWriteCloser
from libp2p.io.exceptions import IOException


class P2PWebSocketConnection(ReadWriteCloser):
    """
    Wraps a raw trio.abc.Stream from an established websocket connection.
    This bypasses message-framing issues and provides the raw stream
    that libp2p protocols expect.
    """

    _stream: Stream

    def __init__(self, stream: Stream):
        self._stream = stream

    async def write(self, data: bytes) -> None:
        try:
            await self._stream.send_all(data)
        except Exception as e:
            raise IOException from e

    async def read(self, n: int | None = None) -> bytes:
        """
        Read up to n bytes (if n is given), else read up to 64KiB.
        """
        try:
            if n is None:
                # read a reasonable chunk
                return await self._stream.receive_some(2**16)
            return await self._stream.receive_some(n)
        except Exception as e:
            raise IOException from e

    async def close(self) -> None:
        await self._stream.aclose()

    def get_remote_address(self) -> tuple[str, int] | None:
        sock = getattr(self._stream, "socket", None)
        if sock:
            try:
                addr = sock.getpeername()
                if isinstance(addr, tuple) and len(addr) >= 2:
                    return str(addr[0]), int(addr[1])
            except OSError:
                return None
        return None
