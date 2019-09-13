import asyncio
from typing import Any  # noqa: F401
from typing import Awaitable, Dict, List, Optional, Tuple

from libp2p.peer.id import ID
from libp2p.security.secure_conn_interface import ISecureConn
from libp2p.stream_muxer.abc import IMuxedConn, IMuxedStream
from libp2p.typing import TProtocol
from libp2p.utils import (
    decode_uvarint_from_stream,
    encode_uvarint,
    encode_varint_prefixed,
    read_varint_prefixed_bytes,
)

from .constants import HeaderTags
from .datastructures import StreamID
from .exceptions import MplexUnavailable
from .mplex_stream import MplexStream

MPLEX_PROTOCOL_ID = TProtocol("/mplex/6.7.0")


class Mplex(IMuxedConn):
    """
    reference: https://github.com/libp2p/go-mplex/blob/master/multiplex.go
    """

    secured_conn: ISecureConn
    peer_id: ID
    # TODO: `dataIn` in go implementation. Should be size of 8.
    # TODO: Also, `dataIn` is closed indicating EOF in Go. We don't have similar strategies
    #   to let the `MplexStream`s know that EOF arrived (#235).
    next_channel_id: int
    streams: Dict[StreamID, MplexStream]
    streams_lock: asyncio.Lock
    new_stream_queue: "asyncio.Queue[IMuxedStream]"
    event_shutting_down: asyncio.Event
    event_closed: asyncio.Event

    _tasks: List["asyncio.Future[Any]"]

    # TODO: `generic_protocol_handler` should be refactored out of mplex conn.
    def __init__(self, secured_conn: ISecureConn, peer_id: ID) -> None:
        """
        create a new muxed connection
        :param secured_conn: an instance of ``ISecureConn``
        :param generic_protocol_handler: generic protocol handler
        for new muxed streams
        :param peer_id: peer_id of peer the connection is to
        """
        self.secured_conn = secured_conn

        self.next_channel_id = 0

        # Set peer_id
        self.peer_id = peer_id

        # Mapping from stream ID -> buffer of messages for that stream
        self.streams = {}
        self.streams_lock = asyncio.Lock()
        self.new_stream_queue = asyncio.Queue()
        self.event_shutting_down = asyncio.Event()
        self.event_closed = asyncio.Event()

        self._tasks = []

        # Kick off reading
        self._tasks.append(asyncio.ensure_future(self.handle_incoming()))

    @property
    def initiator(self) -> bool:
        return self.secured_conn.initiator

    async def close(self) -> None:
        """
        close the stream muxer and underlying secured connection
        """
        if self.event_shutting_down.is_set():
            return
        # Set the `event_shutting_down`, to allow graceful shutdown.
        self.event_shutting_down.set()
        await self.secured_conn.close()
        # Blocked until `close` is finally set.
        await self.event_closed.wait()

    def is_closed(self) -> bool:
        """
        check connection is fully closed
        :return: true if successful
        """
        return self.event_closed.is_set()

    def _get_next_channel_id(self) -> int:
        """
        Get next available stream id
        :return: next available stream id for the connection
        """
        next_id = self.next_channel_id
        self.next_channel_id += 1
        return next_id

    async def _initialize_stream(self, stream_id: StreamID, name: str) -> MplexStream:
        stream = MplexStream(name, stream_id, self)
        async with self.streams_lock:
            self.streams[stream_id] = stream
        return stream

    async def open_stream(self) -> IMuxedStream:
        """
        creates a new muxed_stream
        :return: a new ``MplexStream``
        """
        channel_id = self._get_next_channel_id()
        stream_id = StreamID(channel_id=channel_id, is_initiator=True)
        # Default stream name is the `channel_id`
        name = str(channel_id)
        stream = await self._initialize_stream(stream_id, name)
        await self.send_message(HeaderTags.NewStream, name.encode(), stream_id)
        return stream

    async def _wait_until_shutting_down_or_closed(self, coro: Awaitable[Any]) -> Any:
        task_coro = asyncio.ensure_future(coro)
        task_wait_closed = asyncio.ensure_future(self.event_closed.wait())
        task_wait_shutting_down = asyncio.ensure_future(self.event_shutting_down.wait())
        done, pending = await asyncio.wait(
            [task_coro, task_wait_closed, task_wait_shutting_down],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for fut in pending:
            fut.cancel()
        if task_wait_closed in done:
            raise MplexUnavailable("Mplex is closed")
        if task_wait_shutting_down in done:
            raise MplexUnavailable("Mplex is shutting down")
        return task_coro.result()

    async def accept_stream(self) -> IMuxedStream:
        """
        accepts a muxed stream opened by the other end
        """
        return await self._wait_until_shutting_down_or_closed(
            self.new_stream_queue.get()
        )

    async def send_message(
        self, flag: HeaderTags, data: Optional[bytes], stream_id: StreamID
    ) -> int:
        """
        sends a message over the connection
        :param header: header to use
        :param data: data to send in the message
        :param stream_id: stream the message is in
        """
        # << by 3, then or with flag
        header = encode_uvarint((stream_id.channel_id << 3) | flag.value)

        if data is None:
            data = b""

        _bytes = header + encode_varint_prefixed(data)

        return await self._wait_until_shutting_down_or_closed(
            self.write_to_stream(_bytes)
        )

    async def write_to_stream(self, _bytes: bytes) -> int:
        """
        writes a byte array to a secured connection
        :param _bytes: byte array to write
        :return: length written
        """
        await self.secured_conn.write(_bytes)
        return len(_bytes)

    async def handle_incoming(self) -> None:
        """
        Read a message off of the secured connection and add it to the corresponding message buffer
        """
        # TODO Deal with other types of messages using flag (currently _)

        while True:
            try:
                channel_id, flag, message = await self._wait_until_shutting_down_or_closed(
                    self.read_message()
                )
            except (MplexUnavailable, ConnectionResetError) as error:
                print(f"!@# handle_incoming: read_message: exception={error}")
                break
            if channel_id is not None and flag is not None and message is not None:
                stream_id = StreamID(channel_id=channel_id, is_initiator=bool(flag & 1))
                is_stream_id_seen: bool
                stream: MplexStream
                async with self.streams_lock:
                    is_stream_id_seen = stream_id in self.streams
                    if is_stream_id_seen:
                        stream = self.streams[stream_id]
                # Other consequent stream message should wait until the stream get accepted
                # TODO: Handle more tags, and refactor `HeaderTags`
                if flag == HeaderTags.NewStream.value:
                    if is_stream_id_seen:
                        # `NewStream` for the same id is received twice...
                        # TODO: Shutdown
                        pass
                    mplex_stream = await self._initialize_stream(
                        stream_id, message.decode()
                    )
                    try:
                        await self._wait_until_shutting_down_or_closed(
                            self.new_stream_queue.put(mplex_stream)
                        )
                    except MplexUnavailable:
                        break
                elif flag in (
                    HeaderTags.MessageInitiator.value,
                    HeaderTags.MessageReceiver.value,
                ):
                    if not is_stream_id_seen:
                        # We receive a message of the stream `stream_id` which is not accepted
                        #   before. It is abnormal. Possibly disconnect?
                        # TODO: Warn and emit logs about this.
                        continue
                    async with stream.close_lock:
                        if stream.event_remote_closed.is_set():
                            # TODO: Warn "Received data from remote after stream was closed by them. (len = %d)"  # noqa: E501
                            continue
                    try:
                        await self._wait_until_shutting_down_or_closed(
                            stream.incoming_data.put(message)
                        )
                    except MplexUnavailable:
                        break
                elif flag in (
                    HeaderTags.CloseInitiator.value,
                    HeaderTags.CloseReceiver.value,
                ):
                    if not is_stream_id_seen:
                        continue
                    # NOTE: If remote is already closed, then return: Technically a bug
                    #   on the other side. We should consider killing the connection.
                    async with stream.close_lock:
                        if stream.event_remote_closed.is_set():
                            continue
                    is_local_closed: bool
                    async with stream.close_lock:
                        stream.event_remote_closed.set()
                        is_local_closed = stream.event_local_closed.is_set()
                    # If local is also closed, both sides are closed. Then, we should clean up
                    #   the entry of this stream, to avoid others from accessing it.
                    if is_local_closed:
                        async with self.streams_lock:
                            del self.streams[stream_id]
                elif flag in (
                    HeaderTags.ResetInitiator.value,
                    HeaderTags.ResetReceiver.value,
                ):
                    if not is_stream_id_seen:
                        # This is *ok*. We forget the stream on reset.
                        continue
                    async with stream.close_lock:
                        if not stream.event_remote_closed.is_set():
                            stream.event_reset.set()

                            stream.event_remote_closed.set()
                        # If local is not closed, we should close it.
                        if not stream.event_local_closed.is_set():
                            stream.event_local_closed.set()
                    async with self.streams_lock:
                        del self.streams[stream_id]
                else:
                    # TODO: logging
                    if is_stream_id_seen:
                        await stream.reset()

            # Force context switch
            await asyncio.sleep(0)
        await self._cleanup()

    async def read_message(self) -> Tuple[int, int, bytes]:
        """
        Read a single message off of the secured connection
        :return: stream_id, flag, message contents
        """

        # FIXME: No timeout is used in Go implementation.
        # Timeout is set to a relatively small value to alleviate wait time to exit
        #  loop in handle_incoming
        header = await decode_uvarint_from_stream(self.secured_conn)
        # TODO: Handle the case of EOF and other exceptions?
        try:
            message = await asyncio.wait_for(
                read_varint_prefixed_bytes(self.secured_conn), timeout=5
            )
        except asyncio.TimeoutError:
            # TODO: Investigate what we should do if time is out.
            return None, None, None

        flag = header & 0x07
        channel_id = header >> 3

        return channel_id, flag, message

    async def _cleanup(self) -> None:
        if not self.event_shutting_down.is_set():
            self.event_shutting_down.set()
        async with self.streams_lock:
            for stream in self.streams.values():
                async with stream.close_lock:
                    if not stream.event_remote_closed.is_set():
                        stream.event_remote_closed.set()
                        stream.event_reset.set()
                        stream.event_local_closed.set()
            self.streams = None
        self.event_closed.set()
