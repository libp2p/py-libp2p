from abc import ABC, abstractmethod

class INetwork(ABC):

    @abstractmethod
    def set_stream_handler(self, stream_handler):
        """
        :param stream_handler: a stream handler instance
        :return: true if successful
        """
        pass

    @abstractmethod
    def new_stream(self, peer_id, protocol_id):
        """
        :param peer_id: peer_id of destination
        :param protocol_id: protocol id
        :return: stream instance
        """
        pass

    @abstractmethod
    def listen(self, *args):
        """
        :param *args: one or many multiaddrs to start listening on
        :return: True if at least one success
        """
        pass
