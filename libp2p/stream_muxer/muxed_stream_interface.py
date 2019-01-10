from abc import ABC, abstractmethod


class IMuxedStream(ABC):

    @abstractmethod
    def read(self):
        """
        reads from the underlying muxed_conn
        :return: bytes of input
        """

    @abstractmethod
    def write(self, _bytes):
        """
        writes to the underlying muxed_conn
        :return: number of bytes written
        """

    @abstractmethod
    def close(self):
        """
        close the underlying muxed_conn
        :return: true if successful
        """

    @abstractmethod
    def reset(self):
        """
        closes both ends of the stream
        tells this remote side to hang up
        :return: error/exception
        """

    @abstractmethod
    def set_deadline(self, ttl):
        """
        set deadline for muxed stream
        :return: a new stream
        """
