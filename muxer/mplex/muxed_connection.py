import asyncio
from .utils import encode_uvarint, decode_uvarint
from .muxed_connection_interface import IMuxedConn
from .muxed_stream import MuxedStream

class MuxedConn(IMuxedConn):
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
        self.buffers = {}
        self.streams = {}

        self.add_incoming_task()

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
        pass

    def read_buffer(self, stream_id):
        data = self.buffers[stream_id]
        self.buffers[stream_id] = bytearray()
        return data

    def open_stream(self, protocol_id, stream_id, peer_id, multi_addr):
        """
        creates a new muxed_stream
        :return: a new stream
        """
        stream = MuxedStream(peer_id, multi_addr, self)
        self.streams[stream_id] = stream
        self.buffers[stream_id] = bytearray()
        return stream


    def accept_stream(self):
        """
        accepts a muxed stream opened by the other end
        :return: the accepted stream
        """
        pass

    def send_message(self, flag, data, stream_id):
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
        data_length = encode_uvarint(len(data))
        _bytes = header + data_length + data
        return self.write_to_stream(_bytes)

    async def write_to_stream(self, _bytes):
        self.raw_conn.writer.write(_bytes)
        await self.raw_conn.writer.drain()
        return len(_bytes)

    async def handle_incoming(self):
        data = bytearray()
        while True:
            chunk = self.raw_conn.reader.read(100)
            if not chunk:
                break
            data += chunk
        header, end_index = decode_uvarint(data, 0)
        length, end_index = decode_uvarint(data, end_index)
        message = data[end_index, end_index + length]

        # Deal with other types of messages
        flag = header & 0x07
        stream_id = header >> 3

        self.buffers[stream_id] = self.buffers[stream_id] + message
        # Read header
        # Read message length
        # Read message into corresponding buffer


    def add_incoming_task(self):
        loop = asyncio.get_event_loop()
        handle_incoming_task = loop.create_task(self.handle_incoming())
        handle_incoming_task.add_done_callback(self.add_incoming_task)
