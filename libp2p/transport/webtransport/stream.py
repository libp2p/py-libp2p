"""
WebTransport stream implementing :class:`IMuxedStream`.

Byte-oriented (no protobuf framing) — payload rides on aioquic WebTransport
streams after the ``WEBTRANSPORT_STREAM`` header.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import trio

from libp2p.abc import IMuxedStream
from libp2p.stream_muxer.exceptions import MuxedStreamEOF

from .exceptions import WebTransportStreamError

if TYPE_CHECKING:
    from .connection import WebTransportConnection

logger = logging.getLogger(__name__)


class WebTransportStream(IMuxedStream):
    """A single bidirectional WebTransport stream."""

    def __init__(
        self,
        connection: WebTransportConnection,
        stream_id: int,
        is_initiator: bool,
    ) -> None:
        self.muxed_conn = connection
        self._wt_conn = connection
        self._stream_id = stream_id
        self._is_initiator = is_initiator
        self._closed = False
        self._read_closed = False
        self._write_closed = False
        self._deadline: float = 0.0

        self._read_send: trio.MemorySendChannel[bytes]
        self._read_recv: trio.MemoryReceiveChannel[bytes]
        self._read_send, self._read_recv = trio.open_memory_channel[bytes](64)
        self._buf = bytearray()

    @property
    def stream_id(self) -> int:
        return self._stream_id

    def get_remote_address(self) -> tuple[str, int] | None:
        get_addr = getattr(self.muxed_conn, "get_remote_address", None)
        if callable(get_addr):
            return get_addr()  # type: ignore[no-any-return]
        return None

    def on_data(self, data: bytes, stream_ended: bool = False) -> None:
        """Called by the connection when WT stream data arrives."""
        if data:
            try:
                self._read_send.send_nowait(data)
            except (trio.WouldBlock, trio.ClosedResourceError):
                logger.debug(
                    "Dropping data on stream %d (queue full/closed)",
                    self._stream_id,
                )
        if stream_ended:
            self._read_closed = True
            try:
                self._read_send.send_nowait(b"")
            except (trio.WouldBlock, trio.ClosedResourceError):
                pass
            try:
                self._read_send.close()
            except trio.ClosedResourceError:
                pass

    async def read(self, n: int | None = None) -> bytes:
        if self._closed and not self._buf:
            raise WebTransportStreamError("Stream is closed")

        if self._buf:
            if n is None or n >= len(self._buf):
                data = bytes(self._buf)
                self._buf.clear()
                return data
            data = bytes(self._buf[:n])
            del self._buf[:n]
            return data

        try:
            if self._deadline > 0:
                timeout = max(0.0, self._deadline - trio.current_time())
                with trio.move_on_after(timeout) as scope:
                    chunk = await self._read_recv.receive()
                if scope.cancelled_caught:
                    raise WebTransportStreamError("Read deadline exceeded")
            else:
                chunk = await self._read_recv.receive()
        except trio.EndOfChannel as e:
            if self._buf:
                data = bytes(self._buf)
                self._buf.clear()
                return data
            raise MuxedStreamEOF("Stream closed by remote") from e

        if not chunk:
            raise MuxedStreamEOF("Stream closed by remote")

        if n is None or n >= len(chunk):
            return chunk
        self._buf.extend(chunk[n:])
        return chunk[:n]

    async def write(self, data: bytes) -> None:
        if self._write_closed or self._closed:
            raise WebTransportStreamError("Write side is closed")
        if not data:
            return
        await self._wt_conn._send_stream_data(self._stream_id, data)

    async def close(self) -> None:
        """Close the write side (send FIN)."""
        if self._write_closed:
            return
        self._write_closed = True
        try:
            await self._wt_conn._send_stream_data(self._stream_id, b"", end_stream=True)
        except Exception:
            logger.debug(
                "Error sending FIN on stream %d",
                self._stream_id,
                exc_info=True,
            )
        if self._read_closed:
            self._closed = True

    async def reset(self) -> None:
        self._closed = True
        self._read_closed = True
        self._write_closed = True
        try:
            self._read_send.close()
        except trio.ClosedResourceError:
            pass
        try:
            await self._wt_conn._reset_stream(self._stream_id)
        except Exception:
            pass

    def set_deadline(self, ttl: int) -> None:
        if ttl <= 0:
            self._deadline = 0.0
        else:
            self._deadline = trio.current_time() + float(ttl)

    async def __aenter__(self) -> WebTransportStream:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        await self.close()
