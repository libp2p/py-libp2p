import asyncio
import queue
from threading import Thread
from .utils import encode_uvarint, decode_uvarint
from .mplex_stream import MplexStream
from ..muxed_connection_interface import IMuxedConn


class Mplex(IMuxedConn):
    """
    reference: https://github.com/libp2p/go-mplex/blob/master/multiplex.go
    """

    def __init__(self, conn, initiator):
        """
        create a new muxed connection
        :param conn: an instance of raw connection
        :param initiator: boolean to prevent multiplex with self
        """
        self.raw_conn = conn
        self.initiator = initiator

        # Mapping from stream ID -> buffer of messages for that stream
        self.buffers = {}

        self.stream_queue = asyncio.Queue()
        self.conn_lock = asyncio.Lock()
        self.buffers_lock = asyncio.Lock()
        self._next_id = 0

        # The initiator need not read upon construction time.
        # It should read when the user decides that it wants to read from the constructed stream.
        if not initiator:
            asyncio.ensure_future(self.handle_incoming())

    def _next_stream_id(self):
        next_id = self._next_id
        self._next_id += 1
        return next_id

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
        # Empty buffer or nonexistent stream
        # TODO: propagate up timeout exception and catch
        if stream_id not in self.buffers or self.buffers[stream_id].empty():
            await self.handle_incoming()
        if stream_id in self.buffers:
            return await self._read_buffer_exists(stream_id)
        else:
            print("after handle incoming, buffer still wasnt created")
            return None

    async def _read_buffer_exists(self, stream_id):
        try:
            data = await asyncio.wait_for(self.buffers[stream_id].get(), timeout=5)
            return data
        except asyncio.TimeoutError:
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
        stream_id = self._next_stream_id()
        stream = MplexStream(stream_id, multi_addr, self)
        self.buffers[stream_id] = asyncio.Queue()
        return stream

    async def accept_stream(self):
        """
        accepts a muxed stream opened by the other end
        :return: the accepted stream
        """
        # TODO update to pull out protocol_id from message
        protocol_id = "/echo/1.0.0"
        stream_id = await self.stream_queue.get()
        stream = MplexStream(stream_id, False, self)
        return stream, stream_id, protocol_id

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

        # data_length = encode_uvarint(len(data))
        # _bytes = header + data_length + data
        print(str(_bytes) + " was written")
        return await self.write_to_stream(_bytes)

    async def write_to_stream(self, _bytes):
        self.raw_conn.writer.write(_bytes)
        await self.raw_conn.writer.drain()
        print("_bytes was written" + str(self.initiator))
        return len(_bytes)

    async def handle_incoming(self):
        # print('handle_incoming entered')
        data = bytearray()
        try:
            print("about to read - in handle incoming" + str(self.initiator))
            chunk = await asyncio.wait_for(self.raw_conn.reader.read(1024), timeout=6)
            data += chunk
            print("read finished! - " + str(chunk) + str(self.initiator))
            header, end_index = decode_uvarint(data, 0)
            length, end_index = decode_uvarint(data, end_index)
            message = data[end_index:end_index + length + 1]

            # Deal with other types of messages
            # TODO use flag
            # flag = header & 0x07
            stream_id = header >> 3
            if stream_id not in self.buffers:
                self.buffers[stream_id] = asyncio.Queue()
                print("creating queue!" + str(self.initiator))
                await self.stream_queue.put(stream_id)
            else:
                print("stream_id " + str(stream_id) + " was already in buffers according to handle_incoming")
            await self.buffers[stream_id].put(message)
            print("put into buffer")
        except asyncio.TimeoutError:
            print('timeout! ' + str(self.initiator))

    async def read_message(self):
        data = bytearray()
        try:
            chunk = await asyncio.wait_for(self.raw_conn.reader.read(1024), timeout=5)
            data += chunk

            header, end_index = decode_uvarint(data, 0)
            length, end_index = decode_uvarint(data, end_index)

            message = data[end_index:end_index + length + 1]
        except asyncio.TimeoutError:
            print('timeout!')
            return None, None, None

        header, end_index = decode_uvarint(data, 0)
        length, end_index = decode_uvarint(data, end_index)

        message = data[end_index:end_index + length + 1]

        flag = header & 0x07
        stream_id = header >> 3
        
        return stream_id, flag, message
