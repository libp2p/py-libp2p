from .network_interface import INetwork
from stream import Stream

class Swarm(INetwork):

    def __init__(self, my_peer_id, peer_store):
        self.my_peer_id = my_peer_id
        self.peer_store = peer_store
        self.stream_handlers = {}

    def set_stream_handler(self, protocol_id, stream_handler):
        """
        :param stream_handler: a stream handler instance
        :return: true if successful
        """
        self.stream_handlers[protocol_id] = stream_handler
        return True

    def new_stream(self, peer_id):
        """
        :param peer_id: peer_id of destination
        :return: stream instance
        """
        stream = Stream(peer_id)
        return stream

    def listen(self, *args):
        """
        :param *args: one or many multiaddrs to start listening on
        :return: true if at least one success
        """
        pass

    def listen(self, *args):
        """
        :param *args: one or many multiaddrs to start listening on
        :return: true if at least one success
        """
        pass
