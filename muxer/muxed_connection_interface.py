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
    def open_stream(self):
        """
        creates a new muxed_stream
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
