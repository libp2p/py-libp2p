import uuid
from .network_interface import INetwork
from .stream.net_stream import NetStream

class Swarm(INetwork):

    def __init__(self, my_peer_id, peerstore, upgrader):
        self.my_peer_id = my_peer_id
        self.peerstore = peerstore
        self.upgrader = upgrader
        self.connections = dict()
        self.listeners = dict()

    def set_stream_handler(self, stream_handler):
        """
        :param stream_handler: a stream handler instance
        :return: true if successful
        """
        pass

    def new_stream(self, peer_id, protocol_id):
        """
        :param peer_id: peer_id of destination
        :param protocol_id: protocol id
        :return: net stream instance
        """
        muxed_conn = None
        if peer_id in self.connections:
            """
            If muxed connection already exists for peer_id,
            set muxed connection equal to
            existing muxed connection
            """
            muxed_conn = self.connections[peer_id]
        else:
            # Get peer info from peer store
            addrs = self.peerstore.addrs(peer_id)

            # Transport dials peer (gets back a raw conn)
            if not addrs:
                raise SwarmException("No known addresses to peer")
            first_addr = addrs[0]
            raw_conn = self.transport.dial(first_addr)

            # Use upgrader to upgrade raw conn to muxed conn
            muxed_conn = self.upgrader.upgrade_connection(raw_conn, True)

            # Store muxed connection in connections
            self.connections[peer_id] = muxed_conn

        # Use muxed conn to open stream, which returns
        # a muxed stream
        stream_id = str(uuid.uuid4())
        muxed_stream = muxed_conn.open_stream(protocol_id, stream_id, peer_id, first_addr)

        # Create a net stream
        net_stream = NetStream(muxed_stream)

        return net_stream

    def listen(self, *args):
        """
        :param *args: one or many multiaddrs to start listening on
        :return: true if at least one success
        """

        # Create a closure C that takes in a multiaddr and 
        # returns a function object O that takes in a reader and writer.
        # This function O looks up the stream handler
        # for the given protocol, creates the net_stream 
        # for the listener and calls the stream handler function
        # passing in the net_stream

        # For each multiaddr in args
            # Check if a listener for multiaddr exists already
            # If listener already exists, continue
            # Otherwise, do the following:
                # Pass multiaddr into C and get back function H
                # listener = transport.create_listener(H)
                # Call listener listen with the multiaddr
                # Map multiaddr to listener

        return True

    def add_transport(self, transport):
        # TODO: Support more than one transport
        self.transport = transport

class SwarmException(Exception):
    pass
