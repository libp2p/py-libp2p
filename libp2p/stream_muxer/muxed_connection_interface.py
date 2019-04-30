from abc import ABC, abstractmethod


class IMuxedConn(ABC):
    """
    reference: https://github.com/libp2p/go-stream-muxer/blob/master/muxer.go
    """

    @abstractmethod
    def __init__(self, conn, generic_protocol_handler, peer_id):
        """
        create a new muxed connection
        :param conn: an instance of secured connection
        :param generic_protocol_handler: generic protocol handler
        for new muxed streams
        :param peer_id: peer_id of peer the connection is to
        """

    @abstractmethod
    def close(self):
        """
        close connection
        :return: true if successful
        """

    @abstractmethod
    def is_closed(self):
        """
        check connection is fully closed
        :return: true if successful
        """

    @abstractmethod
    def open_stream(self, protocol_id, multi_addr):
        """
        creates a new muxed_stream
        :param protocol_id: protocol_id of stream
        :param multi_addr: multi_addr that stream connects to
        :return: a new stream
        """

    @abstractmethod
    def accept_stream(self):
        """
        accepts a muxed stream opened by the other end
        :return: the accepted stream
        """
