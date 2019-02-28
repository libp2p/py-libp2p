from abc import ABC, abstractmethod


class INotifee(ABC):

    @abstractmethod
    def opened_stream(self, network, stream):
        """
        :param network: network the stream was opened on
        :param stream: stream that was opened
        """

    @abstractmethod
    def closed_stream(self, network, stream):
        """
        :param network: network the stream was closed on
        :param stream: stream that was closed
        """

    @abstractmethod
    def connected(self, network, conn):
        """
        :param network: network the connection was opened on
        :param conn: connection that was opened
        """

    @abstractmethod
    def disconnected(self, network, conn):
        """
        :param network: network the connection was closed on
        :param conn: connection that was closed
        """

    @abstractmethod
    def listen(self, network, multiaddr):
        """
        :param network: network the listener is listening on
        :param multiaddr: multiaddress listener is listening on
        """

    @abstractmethod
    def listen_close(self, network, multiaddr):
        """
        :param network: network the connection was opened on
        :param multiaddr: multiaddress listener is no longer listening on
        """
