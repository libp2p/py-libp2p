"""
Yamux stream multiplexer implementation for py-libp2p.
This is the preferred multiplexing protocol due to its performance and feature set.
Mplex is also available for legacy compatibility but may be deprecated in the future.
"""
import logging
import struct
from typing import (
    Optional,
)

import trio
from trio import (
    MemoryReceiveChannel,
    MemorySendChannel,
    Nursery,
)

from libp2p.abc import (
    IMuxedConn,
    IMuxedStream,
    ISecureConn,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.stream_muxer.exceptions import (
    MuxedStreamError,
)

PROTOCOL_ID = "/yamux/1.0.0"
TYPE_DATA = 0x0
TYPE_WINDOW_UPDATE = 0x1
TYPE_PING = 0x2
TYPE_GO_AWAY = 0x3
FLAG_SYN = 0x1
FLAG_ACK = 0x2
FLAG_FIN = 0x4
FLAG_RST = 0x8
HEADER_SIZE = 12


class YamuxStream(IMuxedStream):
    def __init__(self, stream_id: int, conn: "Yamux", is_initiator: bool) -> None:
        self.stream_id = stream_id
        self.conn = conn
        self.is_initiator = is_initiator
        self.closed = False

    async def write(self, data: bytes) -> None:
        if self.closed:
            raise MuxedStreamError("Stream is closed")
        header = struct.pack("!BBHII", 0, TYPE_DATA, 0, self.stream_id, len(data))
        await self.conn.secured_conn.write(header + data)

    async def read(self, n: int = -1) -> bytes:
        return await self.conn.read_stream(self.stream_id, n)

    async def close(self) -> None:
        if not self.closed:
            logging.debug(f"Closing stream {self.stream_id}")
            header = struct.pack("!BBHII", 0, TYPE_DATA, FLAG_FIN, self.stream_id, 0)
            await self.conn.secured_conn.write(header)
            self.closed = True

    async def reset(self) -> None:
        if not self.closed:
            logging.debug(f"Resetting stream {self.stream_id}")
            header = struct.pack("!BBHII", 0, TYPE_DATA, FLAG_RST, self.stream_id, 0)
            await self.conn.secured_conn.write(header)
            self.closed = True

    def set_deadline(self, ttl: int) -> bool:
        return False

    def get_remote_address(self) -> Optional[tuple[str, int]]:
        """
        Returns the remote address of the underlying connection.
        """
        # Delegate to the secured_conn's get_remote_address method
        if hasattr(self.conn.secured_conn, "get_remote_address"):
            remote_addr = self.conn.secured_conn.get_remote_address()
            # Ensure the return value matches tuple[str, int] | None
            if (
                remote_addr is None
                or isinstance(remote_addr, tuple)
                and len(remote_addr) == 2
            ):
                return remote_addr
            else:
                raise ValueError(
                    "Underlying connection returned an unexpected address format"
                )
        else:
            # Return None if the underlying connection doesn’t provide this info
            return None


class Yamux(IMuxedConn):
    def __init__(
        self,
        secured_conn: ISecureConn,
        peer_id: ID,
        is_initiator: Optional[bool] = None,
    ) -> None:
        self.secured_conn = secured_conn
        self.peer_id = peer_id
        self.is_initiator_value = (
            is_initiator if is_initiator is not None else secured_conn.is_initiator
        )
        self.next_stream_id = 1 if self.is_initiator else 2
        self.streams: dict[int, YamuxStream] = {}
        self.streams_lock = trio.Lock()
        self.new_stream_send_channel: MemorySendChannel[YamuxStream]
        self.new_stream_receive_channel: MemoryReceiveChannel[YamuxStream]
        (
            self.new_stream_send_channel,
            self.new_stream_receive_channel,
        ) = trio.open_memory_channel(10)
        self.event_shutting_down = trio.Event()
        self.event_closed = trio.Event()
        self.event_started = trio.Event()
        self.stream_buffers: dict[int, bytearray] = {}
        self.stream_events: dict[int, trio.Event] = {}
        self._nursery: Optional[Nursery] = None

    async def start(self) -> None:
        logging.debug(f"Starting Yamux for {self.peer_id}")
        if self.event_started.is_set():
            return
        async with trio.open_nursery() as nursery:
            self._nursery = nursery
            nursery.start_soon(self.handle_incoming)
            self.event_started.set()

    @property
    def is_initiator(self) -> bool:
        return self.is_initiator_value

    async def close(self) -> None:
        logging.debug("Closing Yamux connection")
        async with self.streams_lock:
            if not self.event_shutting_down.is_set():
                header = struct.pack("!BBHII", 0, TYPE_GO_AWAY, 0, 0, 0)
                await self.secured_conn.write(header)
                self.event_shutting_down.set()
                for stream in self.streams.values():
                    stream.closed = True
                self.stream_buffers.clear()
                self.stream_events.clear()
        await self.secured_conn.close()
        self.event_closed.set()
        await trio.sleep(0.1)

    @property
    def is_closed(self) -> bool:
        return self.event_closed.is_set()

    async def open_stream(self) -> YamuxStream:
        async with self.streams_lock:
            stream_id = self.next_stream_id
            self.next_stream_id += 2
            stream = YamuxStream(stream_id, self, True)
            self.streams[stream_id] = stream
            self.stream_buffers[stream_id] = bytearray()
            self.stream_events[stream_id] = trio.Event()

        header = struct.pack("!BBHII", 0, TYPE_DATA, FLAG_SYN, stream_id, 0)
        logging.debug(f"Sending SYN header for stream {stream_id}")
        await self.secured_conn.write(header)
        return stream

    async def accept_stream(self) -> IMuxedStream:
        logging.debug("Waiting for new stream")
        try:
            stream = await self.new_stream_receive_channel.receive()
            logging.debug(f"Received stream {stream.stream_id}")
            return stream
        except trio.EndOfChannel:
            raise MuxedStreamError("No new streams available")

    async def read_stream(self, stream_id: int, n: int = -1) -> bytes:
        logging.debug(f"Reading from stream {stream_id}, n={n}")
        async with self.streams_lock:
            if stream_id not in self.streams or self.event_shutting_down.is_set():
                logging.debug(f"Stream {stream_id} unknown or connection shutting down")
                return b""
            if self.streams[stream_id].closed and not self.stream_buffers.get(
                stream_id
            ):
                logging.debug(f"Stream {stream_id} closed, returning empty")
                return b""

        while not self.event_shutting_down.is_set():
            async with self.streams_lock:
                buffer = self.stream_buffers.get(stream_id)
                if buffer is None:
                    logging.debug(
                        f"Buffer for stream {stream_id} gone, assuming closed"
                    )
                    return b""
                if buffer:
                    if n == -1 or n >= len(buffer):
                        data = bytes(buffer)
                        buffer.clear()
                    else:
                        data = bytes(buffer[:n])
                        del buffer[:n]
                    logging.debug(
                        f"Returning {len(data)} bytes from stream {stream_id}"
                    )
                    return data
                if self.streams[stream_id].closed:
                    logging.debug(
                        f"Stream {stream_id} closed while waiting, returning empty"
                    )
                    return b""

            logging.debug(f"Waiting for data on stream {stream_id}")
            await self.stream_events[stream_id].wait()
            self.stream_events[stream_id] = trio.Event()

        logging.debug(f"Connection shut down while reading stream {stream_id}")
        return b""

    async def handle_incoming(self) -> None:
        while not self.event_shutting_down.is_set():
            try:
                header = await self.secured_conn.read(HEADER_SIZE)
                if not header or len(header) < HEADER_SIZE:
                    logging.debug("Connection closed or incomplete header")
                    self.event_shutting_down.set()
                    break
                version, typ, flags, stream_id, length = struct.unpack("!BBHII", header)
                logging.debug(
                    f"Received header: type={typ}, flags={flags}, "
                    f"stream_id={stream_id}, length={length}"
                )
                if typ == TYPE_DATA and flags & FLAG_SYN:
                    async with self.streams_lock:
                        if stream_id not in self.streams:
                            stream = YamuxStream(stream_id, self, False)
                            self.streams[stream_id] = stream
                            self.stream_buffers[stream_id] = bytearray()
                            self.stream_events[stream_id] = trio.Event()
                            logging.debug(f"Sending stream {stream_id} to channel")
                            await self.new_stream_send_channel.send(stream)
                elif typ == TYPE_DATA and flags & FLAG_RST:
                    async with self.streams_lock:
                        if stream_id in self.streams:
                            logging.debug(f"Resetting stream {stream_id}")
                            self.streams[stream_id].closed = True
                            self.stream_events[stream_id].set()
                elif typ == TYPE_DATA:
                    data = await self.secured_conn.read(length) if length > 0 else b""
                    async with self.streams_lock:
                        if stream_id in self.streams:
                            self.stream_buffers[stream_id].extend(data)
                            self.stream_events[stream_id].set()
                            if flags & FLAG_FIN:
                                logging.debug(f"Closing stream {stream_id} due to FIN")
                                self.streams[stream_id].closed = True
                elif typ == TYPE_GO_AWAY:
                    logging.debug("Received GO_AWAY, shutting down")
                    self.event_shutting_down.set()
                    break
            except Exception as e:
                logging.error(f"Error in handle_incoming: {type(e).__name__}: {str(e)}")
                self.event_shutting_down.set()
                break
