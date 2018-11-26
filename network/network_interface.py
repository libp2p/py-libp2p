from abc import ABC, abstractmethod


class INetwork(ABC):

    @abstractmethod
    def get_peer_id(self):
        """
        :return: the peer id
        """

    @abstractmethod
    def set_stream_handler(self, protocol_id, stream_handler):
        """
        :param protocol_id: protocol id used on stream
        :param stream_handler: a stream handler instance
        :return: true if successful
        """

    @abstractmethod
    def new_stream(self, peer_id, protocol_id):
        """
        :param peer_id: peer_id of destination
        :param protocol_id: protocol id
        :return: stream instance
        """

    @abstractmethod
    def listen(self, *args):
        """
        :param *args: one or many multiaddrs to start listening on
        :return: True if at least one success
        """
