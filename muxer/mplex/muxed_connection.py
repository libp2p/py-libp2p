import asyncio
from .muxed_connection_interface import IMuxedConn
from transport.stream.Stream import Stream

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

    def open_stream(self, protocol_id, stream_id, peer_id, multi_addr):
        """
        creates a new muxed_stream
        :return: a new stream
        """
        stream = Stream(peer_id, multi_addr, self)
        self.streams[stream_id] = stream
        self.buffers[stream_id] = bytearray()
        return stream


    def accept_stream(self):
        """
        accepts a muxed stream opened by the other end
        :return: the accepted stream
        """
        pass

    def send_message(self, header, data):
        """
        sends a message over the connection
        :param header: header to use
        :param data: data to send in the message
        :return: True if success
        """
        pass

    async def handle_incoming(self):
        data = bytearray()
        while True:
            chunk = self.raw_conn.reader.read(100)
            if not chunk:
                break
            data += chunk

        # Read header
        # Read message length
        # Read message into corresponding buffer


    def add_incoming_task(self):
        loop = asyncio.get_event_loop()
        handle_incoming_task = loop.create_task(self.handle_incoming())
        handle_incoming_task.add_done_callback(self.add_incoming_task)
