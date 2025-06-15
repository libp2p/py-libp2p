import logging

import trio

from libp2p.abc import (
    IMuxedConn,
    IMuxedStream,
    ISecureConn,
)
from libp2p.custom_types import (
    TProtocol,
)
from libp2p.exceptions import (
    ParseError,
)
from libp2p.io.exceptions import (
    IncompleteReadError,
)
from libp2p.network.connection.exceptions import (
    RawConnError,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.utils import (
    decode_uvarint_from_stream,
    encode_uvarint,
    encode_varint_prefixed,
    read_varint_prefixed_bytes,
)

from .constants import (
    HeaderTags,
)
from .datastructures import (
    StreamID,
)
from .exceptions import (
    MplexUnavailable,
)
from .mplex_stream import (
    MplexStream,
)

MPLEX_PROTOCOL_ID = TProtocol("/mplex/6.7.0")
# Ref: https://github.com/libp2p/go-mplex/blob/414db61813d9ad3e6f4a7db5c1b1612de343ace9/multiplex.go#L115  # noqa: E501
MPLEX_MESSAGE_CHANNEL_SIZE = 8

logger = logging.getLogger("libp2p.stream_muxer.mplex.mplex")


class Mplex(IMuxedConn):
    """
    reference: https://github.com/libp2p/go-mplex/blob/master/multiplex.go
    """

    secured_conn: ISecureConn
    peer_id: ID
    next_channel_id: int
    streams: dict[StreamID, MplexStream]
    streams_lock: trio.Lock
    streams_msg_channels: dict[StreamID, "trio.MemorySendChannel[bytes]"]
    new_stream_send_channel: "trio.MemorySendChannel[IMuxedStream]"
    new_stream_receive_channel: "trio.MemoryReceiveChannel[IMuxedStream]"

    event_shutting_down: trio.Event
    event_closed: trio.Event
    event_started: trio.Event

    def __init__(self, secured_conn: ISecureConn, peer_id: ID) -> None:
        """
        Create a new muxed connection.

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
        self.streams_lock = trio.Lock()
        self.streams_msg_channels = {}
        channels = trio.open_memory_channel[IMuxedStream](0)
        self.new_stream_send_channel, self.new_stream_receive_channel = channels
        self.event_shutting_down = trio.Event()
        self.event_closed = trio.Event()
        self.event_started = trio.Event()

    async def start(self) -> None:
        await self.handle_incoming()

    @property
    def is_initiator(self) -> bool:
        return self.secured_conn.is_initiator

    async def close(self) -> None:
        """
        Close the stream muxer and underlying secured connection.
        """
        if self.event_shutting_down.is_set():
            return
        # Set the `event_shutting_down`, to allow graceful shutdown.
        self.event_shutting_down.set()
        await self.secured_conn.close()
        # Blocked until `close` is finally set.
        await self.event_closed.wait()

    @property
    def is_closed(self) -> bool:
        """
        Check connection is fully closed.

        :return: true if successful
        """
        return self.event_closed.is_set()

    def _get_next_channel_id(self) -> int:
        """
        Get next available stream id.

        :return: next available stream id for the connection
        """
        next_id = self.next_channel_id
        self.next_channel_id += 1
        return next_id

    async def _initialize_stream(self, stream_id: StreamID, name: str) -> MplexStream:
        send_channel, receive_channel = trio.open_memory_channel[bytes](
            MPLEX_MESSAGE_CHANNEL_SIZE
        )
        stream = MplexStream(name, stream_id, self, receive_channel)
        async with self.streams_lock:
            self.streams[stream_id] = stream
            self.streams_msg_channels[stream_id] = send_channel
        return stream

    async def open_stream(self) -> IMuxedStream:
        """
        Create a new muxed_stream.

        :return: a new ``MplexStream``
        """
        channel_id = self._get_next_channel_id()
        stream_id = StreamID(channel_id=channel_id, is_initiator=True)
        # Default stream name is the `channel_id`
        name = str(channel_id)
        stream = await self._initialize_stream(stream_id, name)
        await self.send_message(HeaderTags.NewStream, name.encode(), stream_id)
        return stream

    async def accept_stream(self) -> IMuxedStream:
        """
        Accept a muxed stream opened by the other end.
        """
        try:
            return await self.new_stream_receive_channel.receive()
        except trio.EndOfChannel:
            raise MplexUnavailable

    async def send_message(
        self, flag: HeaderTags, data: bytes | None, stream_id: StreamID
    ) -> int:
        """
        Send a message over the connection.

        :param flag: header to use
        :param data: data to send in the message
        :param stream_id: stream the message is in
        """
        # << by 3, then or with flag
        header = encode_uvarint((stream_id.channel_id << 3) | flag.value)

        if data is None:
            data = b""

        _bytes = header + encode_varint_prefixed(data)

        # type ignored TODO figure out return for this and write_to_stream
        return await self.write_to_stream(_bytes)  # type: ignore

    async def write_to_stream(self, _bytes: bytes) -> None:
        """
        Write a byte array to a secured connection.

        :param _bytes: byte array to write
        :return: length written
        """
        try:
            await self.secured_conn.write(_bytes)
        except RawConnError as e:
            raise MplexUnavailable(
                "failed to write message to the underlying connection"
            ) from e

    async def handle_incoming(self) -> None:
        """
        Read a message off of the secured connection and add it to the
        corresponding message buffer.
        """
        self.event_started.set()
        while True:
            try:
                await self._handle_incoming_message()
            except MplexUnavailable as e:
                logger.debug("mplex unavailable while waiting for incoming: %s", e)
                break
        # If we enter here, it means this connection is shutting down.
        # We should clean things up.
        await self._cleanup()

    async def read_message(self) -> tuple[int, int, bytes]:
        """
        Read a single message off of the secured connection.

        :return: stream_id, flag, message contents
        """
        try:
            header = await decode_uvarint_from_stream(self.secured_conn)
        except (ParseError, RawConnError, IncompleteReadError) as error:
            raise MplexUnavailable(
                "failed to read the header correctly from the underlying connection: "
                f"{error}"
            )
        try:
            message = await read_varint_prefixed_bytes(self.secured_conn)
        except (ParseError, RawConnError, IncompleteReadError) as error:
            raise MplexUnavailable(
                "failed to read the message body correctly from the underlying "
                f"connection: {error}"
            )

        flag = header & 0x07
        channel_id = header >> 3

        return channel_id, flag, message

    async def _handle_incoming_message(self) -> None:
        """
        Read and handle a new incoming message.

        :raise MplexUnavailable: `Mplex` encounters fatal error or is shutting down.
        """
        channel_id, flag, message = await self.read_message()
        stream_id = StreamID(channel_id=channel_id, is_initiator=bool(flag & 1))

        if flag == HeaderTags.NewStream.value:
            await self._handle_new_stream(stream_id, message)
        elif flag in (
            HeaderTags.MessageInitiator.value,
            HeaderTags.MessageReceiver.value,
        ):
            await self._handle_message(stream_id, message)
        elif flag in (HeaderTags.CloseInitiator.value, HeaderTags.CloseReceiver.value):
            await self._handle_close(stream_id)
        elif flag in (HeaderTags.ResetInitiator.value, HeaderTags.ResetReceiver.value):
            await self._handle_reset(stream_id)
        else:
            # Receives messages with an unknown flag
            # TODO: logging
            async with self.streams_lock:
                if stream_id in self.streams:
                    stream = self.streams[stream_id]
                    await stream.reset()

    async def _handle_new_stream(self, stream_id: StreamID, message: bytes) -> None:
        async with self.streams_lock:
            if stream_id in self.streams:
                # `NewStream` for the same id is received twice...
                raise MplexUnavailable(
                    f"received NewStream message for existing stream: {stream_id}"
                )
        mplex_stream = await self._initialize_stream(stream_id, message.decode())
        try:
            await self.new_stream_send_channel.send(mplex_stream)
        except trio.ClosedResourceError:
            raise MplexUnavailable

    async def _handle_message(self, stream_id: StreamID, message: bytes) -> None:
        async with self.streams_lock:
            if stream_id not in self.streams:
                # We receive a message of the stream `stream_id` which is not accepted
                #   before. It is abnormal. Possibly disconnect?
                # TODO: Warn and emit logs about this.
                return
            stream = self.streams[stream_id]
            send_channel = self.streams_msg_channels[stream_id]
        async with stream.close_lock:
            if stream.event_remote_closed.is_set():
                # TODO: Warn "Received data from remote after stream was closed by them. (len = %d)"  # noqa: E501
                return
        try:
            send_channel.send_nowait(message)
        except (trio.BrokenResourceError, trio.ClosedResourceError):
            raise MplexUnavailable
        except trio.WouldBlock:
            # `send_channel` is full, reset this stream.
            logger.warning(
                "message channel of stream %s is full: stream is reset", stream_id
            )
            await stream.reset()

    async def _handle_close(self, stream_id: StreamID) -> None:
        async with self.streams_lock:
            if stream_id not in self.streams:
                # Ignore unmatched messages for now.
                return
            stream = self.streams[stream_id]
            send_channel = self.streams_msg_channels[stream_id]
        await send_channel.aclose()
        # NOTE: If remote is already closed, then return: Technically a bug
        #   on the other side. We should consider killing the connection.
        async with stream.close_lock:
            if stream.event_remote_closed.is_set():
                return
        is_local_closed: bool
        async with stream.close_lock:
            stream.event_remote_closed.set()
            is_local_closed = stream.event_local_closed.is_set()
        # If local is also closed, both sides are closed. Then, we should clean up
        #   the entry of this stream, to avoid others from accessing it.
        if is_local_closed:
            async with self.streams_lock:
                self.streams.pop(stream_id, None)

    async def _handle_reset(self, stream_id: StreamID) -> None:
        async with self.streams_lock:
            if stream_id not in self.streams:
                # This is *ok*. We forget the stream on reset.
                return
            stream = self.streams[stream_id]
            send_channel = self.streams_msg_channels[stream_id]
        await send_channel.aclose()
        async with stream.close_lock:
            if not stream.event_remote_closed.is_set():
                stream.event_reset.set()
                stream.event_remote_closed.set()
            # If local is not closed, we should close it.
            if not stream.event_local_closed.is_set():
                stream.event_local_closed.set()
        async with self.streams_lock:
            self.streams.pop(stream_id, None)
            self.streams_msg_channels.pop(stream_id, None)

    async def _cleanup(self) -> None:
        if not self.event_shutting_down.is_set():
            self.event_shutting_down.set()
        async with self.streams_lock:
            for stream_id, stream in self.streams.items():
                async with stream.close_lock:
                    if not stream.event_remote_closed.is_set():
                        stream.event_remote_closed.set()
                        stream.event_reset.set()
                        stream.event_local_closed.set()
                send_channel = self.streams_msg_channels[stream_id]
                await send_channel.aclose()
        self.event_closed.set()
        await self.new_stream_send_channel.aclose()

    def get_remote_address(self) -> tuple[str, int] | None:
        """Delegate to the underlying Mplex connection's secured_conn."""
        return self.secured_conn.get_remote_address()
