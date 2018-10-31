from abc import ABC, abstractmethod

class IMuxedConn(ABC):
    """
    reference: https://github.com/libp2p/go-stream-muxer/blob/master/muxer.go
    """

    # TODO closer

    @abstractmethod
    def is_closed(self):
        """
        check connection is fully closed
        :return: true if successful
        """
        pass

    @abstractmethod
    def open_stream(self, protocol_id, stream_name):
        """
        creates a new muxed_stream
        :param protocol_id: id to be associated with stream
        :param stream_name: name as part of identifier
        :return: a new stream
        """
        pass

    @abstractmethod
    def accept_stream(self):
        """
        accepts a muxed stream opened by the other end
        :return: the accepted stream
        """
        pass
