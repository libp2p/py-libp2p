from abc import ABC, abstractmethod

class IStream(ABC):

    def __init__(self, peer_id, multi_addr, connection):
        self.peer_id = peer_id
        self.multi_addr = multi_addr
        self.connection = connection

    @abstractmethod
    def get_protocol(self):
        """
        :return: protocol id that stream runs on
        """
        pass

    @abstractmethod
    def set_protocol(self, protocol_id):
        """
        :param protocol_id: protocol id that stream runs on
        :return: true if successful
        """
        pass

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
        set deadline for stream
        :return: a new stream
        """
        pass
