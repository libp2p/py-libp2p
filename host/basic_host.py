from .host_interface import IHost


# Upon host creation, host takes in options,
# including the list of addresses on which to listen.
# Host then parses these options and delegates to its Network instance,
# telling it to listen on the given listen addresses.

class BasicHost(IHost):

    # default options constructor
    def __init__(self, _network):
        self.network = _network
        self.peerstore = self.network.peerstore

    def get_id(self):
        """
        :return: peer_id of host
        """
        return self.network.get_peer_id()

    def get_network(self):
        """
        :return: network instance of host
        """
        return self.network

    def get_peerstore(self):
        """
        :return: peerstore of the host (same one as in its network instance)
        """
        return self.peerstore

    def get_mux(self):
        """
        :return: mux instance of host
        """

    def set_stream_handler(self, protocol_id, stream_handler):
        """
        set stream handler for host
        :param protocol_id: protocol id used on stream
        :param stream_handler: a stream handler function
        :return: true if successful
        """
        return self.network.set_stream_handler(protocol_id, stream_handler)


    # protocol_id can be a list of protocol_ids
    # stream will decide which protocol_id to run on
    async def new_stream(self, peer_id, protocol_id):
        """
        :param peer_id: peer_id that host is connecting
        :param protocol_id: protocol id that stream runs on
        :return: true if successful
        """
        # TODO: host should return a mux stream not a raw stream
        stream = await self.network.new_stream(peer_id, protocol_id)
        stream.set_protocol(protocol_id)
        return stream
