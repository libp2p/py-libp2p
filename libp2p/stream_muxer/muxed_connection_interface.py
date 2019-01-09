from abc import ABC, abstractmethod


class IMuxedConn(ABC):
    """
    reference: https://github.com/libp2p/go-stream-muxer/blob/master/muxer.go
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
    def open_stream(self, protocol_id, peer_id, multi_addr):
        """
        creates a new muxed_stream
        :param protocol_id: protocol_id of stream
        :param stream_id: stream_id of stream
        :param peer_id: peer_id that stream connects to
        :param multi_addr: multi_addr that stream connects to
        :return: a new stream
        """

    @abstractmethod
    def accept_stream(self):
        """
        accepts a muxed stream opened by the other end
        :return: the accepted stream
        """
