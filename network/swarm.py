import uuid
from .network_interface import INetwork
from .stream.net_stream import NetStream
from .multiaddr import MultiAddr
from .connection.raw_connection import RawConnection

class Swarm(INetwork):

    def __init__(self, my_peer_id, peerstore, upgrader):
        self.my_peer_id = my_peer_id
        self.peerstore = peerstore
        self.upgrader = upgrader
        self.connections = dict()
        self.listeners = dict()
        self.stream_handlers = dict()

    def set_stream_handler(self, protocol_id, stream_handler):
        """
        :param protocol_id: protocol id used on stream
        :param stream_handler: a stream handler instance
        :return: true if successful
        """
        self.stream_handlers[protocol_id] = stream_handler

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

        # For each multiaddr in args
            # Check if a listener for multiaddr exists already
            # If listener already exists, continue
            # Otherwise, do the following:
                # Pass multiaddr into conn handler
                # Have conn handler delegate to stream handler
                # Call listener listen with the multiaddr
                # Map multiaddr to listener
        for multiaddr_str in args:
            if multiaddr_str in self.listeners:
                return True

            multiaddr = MultiAddr(multiaddr_str)
            multiaddr_dict = multiaddr.to_options()

            def conn_handler(reader, writer):
                # Upgrade reader/write to a net_stream and pass to appropriate stream handler (using multiaddr)
                raw_conn = RawConnection(multiaddr_dict.host, multiaddr_dict.port, reader, writer)
                muxed_conn = self.upgrader.upgrade_connection(raw_conn, False)

                muxed_stream, stream_id, protocol_id = muxed_conn.accept_stream()
                net_stream = NetStream(muxed_stream)
                net_stream.set_protocol(protocol_id)

                # Give to stream handler
                # TODO: handle case when stream handler is set
                self.stream_handlers[protocol_id](net_stream)

            try:
                # Success
                listener = self.transport.create_listener(conn_handler)
                listener.listen(multiaddr)
                return True
            except IOError:
                # Failed. Continue looping.
                print("Failed to connect to: " + multiaddr)

        # No multiaddr succeeded
        return False

    def add_transport(self, transport):
        # TODO: Support more than one transport
        self.transport = transport

class SwarmException(Exception):
    pass
