import logging
import struct

import trio
from trio.typing import (
    ReceiveChannel,
    SendChannel,
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
    def __init__(self, stream_id: int, conn: "Yamux", rw: ISecureConn) -> None:
        self.stream_id = stream_id
        self.conn = conn
        self.rw = rw
        self.closed = False
        self.close_lock = trio.Lock()

    async def write(self, data: bytes) -> None:
        if self.closed:
            raise MuxedStreamError("Stream closed")
        header = struct.pack("!BBHI", 0, TYPE_DATA, 0, self.stream_id, len(data))
        await self.rw.write(header + data)

    async def read(self, n: int = -1) -> bytes:
        if self.closed:
            raise MuxedStreamError("Stream closed")
        return await self.conn.read_stream(self.stream_id, n)

    async def close(self) -> None:
        async with self.close_lock:
            if not self.closed:
                header = struct.pack("!BBHI", 0, TYPE_DATA, FLAG_FIN, self.stream_id, 0)
                await self.rw.write(header)
                self.closed = True

    async def reset(self) -> None:
        async with self.close_lock:
            if not self.closed:
                header = struct.pack("!BBHI", 0, TYPE_DATA, FLAG_RST, self.stream_id, 0)
                await self.rw.write(header)
                self.closed = True

    def set_deadline(self, ttl: int) -> bool:
        return False


class Yamux(IMuxedConn):
    def __init__(self, secured_conn: ISecureConn, peer_id: ID) -> None:
        self.secured_conn = secured_conn
        self.peer_id = peer_id
        self.next_stream_id = 1 if secured_conn.is_initiator else 2
        self.streams: dict[int, YamuxStream] = {}
        self.streams_lock = trio.Lock()
        self.new_stream_send_channel: SendChannel[IMuxedStream]
        self.new_stream_receive_channel: ReceiveChannel[IMuxedStream]
        (
            self.new_stream_send_channel,
            self.new_stream_receive_channel,
        ) = trio.open_memory_channel(0)
        self.event_shutting_down = trio.Event()
        self.event_closed = trio.Event()
        self.event_started = trio.Event()

    async def start(self) -> None:
        self.event_started.set()
        await self.handle_incoming()

    @property
    def is_initiator(self) -> bool:
        return self.secured_conn.is_initiator

    async def close(self) -> None:
        if self.event_shutting_down.is_set():
            return
        self.event_shutting_down.set()
        await self.secured_conn.close()
        await self._cleanup()
        self.event_closed.set()

    @property
    def is_closed(self) -> bool:
        return self.event_closed.is_set()

    async def open_stream(self) -> IMuxedStream:
        async with self.streams_lock:
            stream_id = self.next_stream_id
            self.next_stream_id += 2
            header = struct.pack("!BBHI", 0, TYPE_DATA, FLAG_SYN, stream_id, 0)
            await self.secured_conn.write(header)
            stream = YamuxStream(stream_id, self, self.secured_conn)
            self.streams[stream_id] = stream
            logging.debug(f"Opened stream {stream_id}")
            return stream

    async def accept_stream(self) -> IMuxedStream:
        try:
            return await self.new_stream_receive_channel.receive()
        except trio.EndOfChannel:
            raise MuxedStreamError("No new streams available")

    async def read_stream(self, stream_id: int, n: int) -> bytes:
        while True:
            header = await self.secured_conn.read(HEADER_SIZE)
            if not header:
                raise MuxedStreamError("Connection closed")
            version, typ, flags, sid, length = struct.unpack("!BBHI", header)
            if sid != stream_id:
                continue
            if typ == TYPE_DATA:
                if length == 0 and flags & FLAG_FIN:
                    async with self.streams_lock:
                        if sid in self.streams:
                            self.streams[sid].closed = True
                    return b""
                data = await self.secured_conn.read(length)
                return data
            elif typ == TYPE_GO_AWAY:
                self.event_shutting_down.set()
                raise MuxedStreamError("Connection closed by peer")

    async def handle_incoming(self) -> None:
        while not self.event_shutting_down.is_set():
            try:
                header = await self.secured_conn.read(HEADER_SIZE)
                if not header:
                    raise MuxedStreamError("Connection closed")
                version, typ, flags, stream_id, length = struct.unpack("!BBHI", header)
                logging.debug(
                    f"Received header: type={typ}, flags={flags}, "
                    f"stream_id={stream_id}, length={length}"
                )
                if typ == TYPE_DATA and flags & FLAG_SYN:
                    async with self.streams_lock:
                        if stream_id not in self.streams:
                            stream = YamuxStream(stream_id, self, self.secured_conn)
                            self.streams[stream_id] = stream
                            await self.new_stream_send_channel.send(stream)
                            logging.debug(f"Accepted new stream {stream_id}")
                elif typ == TYPE_DATA and stream_id in self.streams:
                    await self.secured_conn.read(length) if length > 0 else b""
                    if flags & FLAG_FIN:
                        async with self.streams_lock:
                            if stream_id in self.streams:
                                self.streams[stream_id].closed = True
                elif typ == TYPE_GO_AWAY:
                    self.event_shutting_down.set()
                    break
            except Exception as e:
                logging.error(f"Error in handle_incoming: {e}")
                break

    async def _cleanup(self) -> None:
        async with self.streams_lock:
            for stream in self.streams.values():
                async with stream.close_lock:
                    stream.closed = True
        await self.new_stream_send_channel.aclose()
