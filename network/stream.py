from .stream_interface import IStream

class Stream(IStream):

    def __init__(self, peer_id):
        self.peer_id = peer_id

    def protocol(self):
        """
        :return: protocol id that stream runs on
        """
        pass

    def set_protocol(self, protocol_id):
        """
        :param protocol_id: protocol id that stream runs on
        :return: true if successful
        """
        pass

    def read(self):
        """
        read from stream
        :return: bytes of input
        """
        pass

    def write(self, _bytes):
        """
        write to stream
        :return: number of bytes written
        """
        pass

    def close(self):
        """
        close stream
        :return: true if successful
        """
        pass
