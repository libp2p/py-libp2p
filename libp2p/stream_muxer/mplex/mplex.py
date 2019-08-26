import asyncio
from typing import Dict, Optional, Tuple

from libp2p.network.typing import GenericProtocolHandlerFn
from libp2p.peer.id import ID
from libp2p.security.secure_conn_interface import ISecureConn
from libp2p.stream_muxer.abc import IMuxedConn, IMuxedStream
from libp2p.typing import TProtocol
from libp2p.utils import (
    decode_uvarint_from_stream,
    encode_uvarint,
    read_varint_prefixed_bytes,
)

from .constants import HeaderTags
from .exceptions import StreamNotFound
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
    buffers: Dict[int, "asyncio.Queue[bytes]"]
    stream_queue: "asyncio.Queue[int]"
    next_stream_id: int

    # TODO: `generic_protocol_handler` should be refactored out of mplex conn.
    def __init__(
        self,
        secured_conn: ISecureConn,
        generic_protocol_handler: GenericProtocolHandlerFn,
        peer_id: ID,
    ) -> None:
        """
        create a new muxed connection
        :param secured_conn: an instance of ``ISecureConn``
        :param generic_protocol_handler: generic protocol handler
        for new muxed streams
        :param peer_id: peer_id of peer the connection is to
        """
        self.secured_conn = secured_conn

        if self.secured_conn.initiator:
            self.next_stream_id = 0
        else:
            self.next_stream_id = 1

        # Store generic protocol handler
        self.generic_protocol_handler = generic_protocol_handler

        # Set peer_id
        self.peer_id = peer_id

        # Mapping from stream ID -> buffer of messages for that stream
        self.buffers = {}

        self.stream_queue = asyncio.Queue()

        # Kick off reading
        asyncio.ensure_future(self.handle_incoming())

    @property
    def initiator(self) -> bool:
        return self.secured_conn.initiator

    async def close(self) -> None:
        """
        close the stream muxer and underlying secured connection
        """
        await self.secured_conn.close()

    def is_closed(self) -> bool:
        """
        check connection is fully closed
        :return: true if successful
        """
        raise NotImplementedError()

    async def read_buffer(self, stream_id: int) -> bytes:
        """
        Read a message from buffer of the stream specified by `stream_id`,
        check secured connection for new messages.
        `StreamNotFound` is raised when stream `stream_id` is not found in `Mplex`.
        :param stream_id: stream id of stream to read from
        :return: message read
        """
        if stream_id not in self.buffers:
            raise StreamNotFound(f"stream {stream_id} is not found")
        return await self.buffers[stream_id].get()

    async def read_buffer_nonblocking(self, stream_id: int) -> Optional[bytes]:
        """
        Read a message from buffer of the stream specified by `stream_id`, non-blockingly.
        `StreamNotFound` is raised when stream `stream_id` is not found in `Mplex`.
        """
        if stream_id not in self.buffers:
            raise StreamNotFound(f"stream {stream_id} is not found")
        if self.buffers[stream_id].empty():
            return None
        return await self.buffers[stream_id].get()

    def _get_next_stream_id(self) -> int:
        """
        Get next available stream id
        :return: next available stream id for the connection
        """
        next_id = self.next_stream_id
        self.next_stream_id += 2
        return next_id

    async def open_stream(self) -> IMuxedStream:
        """
        creates a new muxed_stream
        :return: a new ``MplexStream``
        """
        stream_id = self._get_next_stream_id()
        name = str(stream_id)
        stream = MplexStream(name, stream_id, True, self)
        self.buffers[stream_id] = asyncio.Queue()
        # Default stream name is the `stream_id`
        await self.send_message(HeaderTags.NewStream, name.encode(), stream_id)
        return stream

    async def accept_stream(self, name: str) -> None:
        """
        accepts a muxed stream opened by the other end
        """
        stream_id = await self.stream_queue.get()
        stream = MplexStream(name, stream_id, False, self)
        asyncio.ensure_future(self.generic_protocol_handler(stream))

    async def send_message(self, flag: HeaderTags, data: bytes, stream_id: int) -> int:
        """
        sends a message over the connection
        :param header: header to use
        :param data: data to send in the message
        :param stream_id: stream the message is in
        """
        # << by 3, then or with flag
        header = (stream_id << 3) | flag.value
        header = encode_uvarint(header)

        if data is None:
            data_length = encode_uvarint(0)
            _bytes = header + data_length
        else:
            data_length = encode_uvarint(len(data))
            _bytes = header + data_length + data

        return await self.write_to_stream(_bytes)

    async def write_to_stream(self, _bytes: bytearray) -> int:
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
            stream_id, flag, message = await self.read_message()

            if stream_id is not None and flag is not None and message is not None:
                if stream_id not in self.buffers:
                    self.buffers[stream_id] = asyncio.Queue()
                    await self.stream_queue.put(stream_id)

                # TODO: Handle more tags, and refactor `HeaderTags`
                if flag == HeaderTags.NewStream.value:
                    # new stream detected on connection
                    await self.accept_stream(message.decode())
                elif flag in (
                    HeaderTags.MessageInitiator.value,
                    HeaderTags.MessageReceiver.value,
                ):
                    await self.buffers[stream_id].put(message)

            # Force context switch
            await asyncio.sleep(0)

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
        stream_id = header >> 3

        return stream_id, flag, message
