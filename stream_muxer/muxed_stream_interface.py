from abc import ABC, abstractmethod


class IMuxedStream(ABC):

    @abstractmethod
    def read(self):
        """
        read from stream
        :return: bytes of input
        """
        pass

    @abstractmethod
    def write(self, _bytes):
        """
        write to stream
        :return: number of bytes written
        """
        pass

    @abstractmethod
    def close(self):
        """
        close stream
        :return: true if successful
        """
        pass

    @abstractmethod
    def reset(self):
        """
        closes both ends of the stream
        tells this remote side to hang up
        :return: error/exception
        """
        pass

    @abstractmethod
    def set_deadline(self, ttl):
        """
        set deadline for muxed stream
        :return: a new stream
        """
        pass
