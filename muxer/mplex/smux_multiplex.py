from .muxed_stream import MuxedStream
from .muxed_connection import MuxedConn

class Multiplex(object):
    """
    reference: https://github.com/whyrusleeping/go-smux-multiplex/blob/master/multiplex.go
    """
    def __init__(self, conn, initiator):
        """
        :param conn: an instance of raw connection
        :param initiator: boolean to prevent multiplex with self
        """
        self.muxed_conn = MuxedConn(conn, initiator)

    def close(self):
        """
        close the stream muxer and underlying raw connection
        """
        return self.muxed_conn.close()

    def is_closed(self):
        """
        check connection is fully closed
        :return: true if successful
        """
        return self.muxed_conn.is_closed()

    def open_stream(self, protocol_id, stream_name):
        """
        creates a new muxed_stream
        :return: a new stream
        """
        return self.muxed_conn.open_stream(protocol_id, stream_name)

    def accept_stream(self, _muxed_stream):
        """
        accepts a muxed stream opened by the other end
        :param _muxed_stream: stream to be accepted
        :return: the accepted stream
        """
        pass

    # def new_conn(raw_conn, is_server):
    #     pass
