from abc import ABC, abstractmethod

class INetwork(ABC):

    def __init__(self, context, my_peer_id, peer_store):
        self.context = context
        self.my_peer_id = my_peer_id
        self.peer_store = peer_store

    @abstractmethod
    def set_stream_handler(self, stream_handler):
        """
        :param stream_handler: a stream handler instance
        :return: true if successful
        """
        pass

    @abstractmethod
    def new_stream(self, context, peer_id):
        """
        :param context: context instance
        :param peer_id: peer_id of destination
        :return: stream instance
        """
        pass
