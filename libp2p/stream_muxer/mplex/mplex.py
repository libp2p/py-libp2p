import asyncio

from .utils import encode_uvarint, decode_uvarint_from_stream, get_flag
from .mplex_stream import MplexStream
from ..muxed_connection_interface import IMuxedConn


class Mplex(IMuxedConn):
    # pylint: disable=too-many-instance-attributes
    """
    reference: https://github.com/libp2p/go-mplex/blob/master/multiplex.go
    """

    def __init__(self, conn, generic_protocol_handler):
        """
        create a new muxed connection
        :param conn: an instance of raw connection
        :param generic_protocol_handler: generic protocol handler
        for new muxed streams
        """
        super(Mplex, self).__init__(conn, generic_protocol_handler)

        self.raw_conn = conn
        self.initiator = conn.initiator

        # Store generic protocol handler
        self.generic_protocol_handler = generic_protocol_handler

        # Mapping from stream ID -> buffer of messages for that stream
        self.buffers = {}

        self.stream_queue = asyncio.Queue()

        # Kick off reading
        asyncio.ensure_future(self.handle_incoming())

    def close(self):
        """
        close the stream muxer and underlying raw connection
        """
        self.raw_conn.close()

    def is_closed(self):
        """
        check connection is fully closed
        :return: true if successful
        """

    async def read_buffer(self, stream_id):
        """
        Read a message from stream_id's buffer, check raw connection for new messages
        :param stream_id: stream id of stream to read from
        :return: message read
        """
        # TODO: propagate up timeout exception and catch
        # TODO: pass down timeout from user and use that
        if stream_id in self.buffers:
            try:
                data = await asyncio.wait_for(self.buffers[stream_id].get(), timeout=3)
                return data
            except asyncio.TimeoutError:
                return None

        # Stream not created yet
        return None

    async def open_stream(self, protocol_id, peer_id, multi_addr):
        """
        creates a new muxed_stream
        :param protocol_id: protocol_id of stream
        :param stream_id: stream_id of stream
        :param peer_id: peer_id that stream connects to
        :param multi_addr: multi_addr that stream connects to
        :return: a new stream
        """
        stream_id = self.raw_conn.next_stream_id()
        stream = MplexStream(stream_id, multi_addr, self)
        self.buffers[stream_id] = asyncio.Queue()
        await self.send_message(get_flag(self.initiator, "NEW_STREAM"), None, stream_id)
        return stream

    async def accept_stream(self):
        """
        accepts a muxed stream opened by the other end
        :return: the accepted stream
        """
        stream_id = await self.stream_queue.get()
        stream = MplexStream(stream_id, False, self)
        asyncio.ensure_future(self.generic_protocol_handler(stream))

    async def send_message(self, flag, data, stream_id):
        """
        sends a message over the connection
        :param header: header to use
        :param data: data to send in the message
        :param stream_id: stream the message is in
        :return: True if success
        """
        # << by 3, then or with flag
        header = (stream_id << 3) | flag
        header = encode_uvarint(header)

        if data is None:
            data_length = encode_uvarint(0)
            _bytes = header + data_length
        else:
            data_length = encode_uvarint(len(data))
            _bytes = header + data_length + data

        return await self.write_to_stream(_bytes)

    async def write_to_stream(self, _bytes):
        """
        writes a byte array to a raw connection
        :param _bytes: byte array to write
        :return: length written
        """
        self.raw_conn.writer.write(_bytes)
        await self.raw_conn.writer.drain()
        return len(_bytes)

    async def handle_incoming(self):
        """
        Read a message off of the raw connection and add it to the corresponding message buffer
        """
        # TODO Deal with other types of messages using flag (currently _)

        while True:
            stream_id, flag, message = await self.read_message()

            if stream_id is not None and flag is not None and message is not None:
                if stream_id not in self.buffers:
                    self.buffers[stream_id] = asyncio.Queue()
                    await self.stream_queue.put(stream_id)

                if flag is get_flag(True, "NEW_STREAM"):
                    # new stream detected on connection
                    await self.accept_stream()

                if message:
                    await self.buffers[stream_id].put(message)

            # Force context switch
            await asyncio.sleep(0)

    async def read_message(self):
        """
        Read a single message off of the raw connection
        :return: stream_id, flag, message contents
        """

        # Timeout is set to a relatively small value to alleviate wait time to exit
        #  loop in handle_incoming
        timeout = 0.1
        try:
            header = await decode_uvarint_from_stream(self.raw_conn.reader, timeout)
            length = await decode_uvarint_from_stream(self.raw_conn.reader, timeout)
            message = await asyncio.wait_for(self.raw_conn.reader.read(length), timeout=timeout)
        except asyncio.TimeoutError:
            return None, None, None

        flag = header & 0x07
        stream_id = header >> 3

        return stream_id, flag, message
