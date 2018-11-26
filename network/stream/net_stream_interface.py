from abc import ABC, abstractmethod


class INetStream(ABC):

    @abstractmethod
    def get_protocol(self):
        """
        :return: protocol id that stream runs on
        """

    @abstractmethod
    def set_protocol(self, protocol_id):
        """
        :param protocol_id: protocol id that stream runs on
        :return: true if successful
        """

    @abstractmethod
    def read(self):
        """
        read from stream
        :return: bytes of input
        """

    @abstractmethod
    def write(self, _bytes):
        """
        write to stream
        :return: number of bytes written
        """

    @abstractmethod
    def close(self):
        """
        close stream
        :return: true if successful
        """
