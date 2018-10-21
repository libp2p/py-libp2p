from .network_interface import INetwork

class Swarm(INetwork):

    def __init__(self, my_peer_id, peer_store):
        self.my_peer_id = my_peer_id
        self.peer_store = peer_store

    def set_stream_handler(self, stream_handler):
        """
        :param stream_handler: a stream handler instance
        :return: true if successful
        """
        pass

    def new_stream(self, peer_id):
        """
        :param peer_id: peer_id of destination
        :return: stream instance
        """
        pass

    def listen(self, *args):
        """
        :param *args: one or many multiaddrs to start listening on
        :return: true if at least one success
        """
        pass
