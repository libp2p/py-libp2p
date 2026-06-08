from __future__ import annotations

import socket
from typing import TYPE_CHECKING

import trio

if TYPE_CHECKING:
    pass


class PeekableStream(trio.abc.Stream):
    """
    Wraps a :class:`trio.abc.Stream` and allows peeking/buffering of the first
    few bytes.

    When `receive_some` is called, it returns buffered data before reading from the
    underlying stream. This is useful for connection multiplexing (cmux) where you
    need to read bytes to determine the protocol without permanently consuming them.
    """

    stream: trio.abc.Stream
    buffer: bytearray

    def __init__(self, stream: trio.abc.Stream, initial_buffer: bytes = b"") -> None:
        self.stream = stream
        self.buffer = bytearray(initial_buffer)

    @property
    def socket(self) -> socket.socket | None:
        """
        Pass-through to underlying socket for address retrieval.

        This property is required by :class:`~libp2p.io.trio.TrioTCPStream` to retrieve
        the remote peer's IP address.
        """
        if hasattr(self.stream, "socket"):
            return getattr(self.stream, "socket")
        return None

    async def receive_some(self, max_bytes: int | None = None) -> bytes:
        if self.buffer:
            if max_bytes is None:
                max_bytes = len(self.buffer)
            data = bytes(self.buffer[:max_bytes])
            self.buffer = self.buffer[max_bytes:]
            return data
        return await self.stream.receive_some(max_bytes)

    async def send_all(self, data: bytes | memoryview) -> None:
        await self.stream.send_all(data)

    async def wait_send_all_might_not_block(self) -> None:
        await self.stream.wait_send_all_might_not_block()

    async def aclose(self) -> None:
        await self.stream.aclose()
