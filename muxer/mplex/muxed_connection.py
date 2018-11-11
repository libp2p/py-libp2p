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

    def close(self):
        """
        close the stream muxer and underlying raw connection
        """
        pass

    def is_closed(self):
        """
        check connection is fully closed
        :return: true if successful
        """
        pass

    def open_stream(self, protocol_id, stream_name, peer_id, multi_addr):
        """
        creates a new muxed_stream
        :return: a new stream
        """
        return Stream(peer_id, multi_addr, self)

    def accept_stream(self):
        """
        accepts a muxed stream opened by the other end
        :return: the accepted stream
        """
        pass
