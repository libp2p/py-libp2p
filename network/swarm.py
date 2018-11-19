import uuid
from .network_interface import INetwork
from .stream.net_stream import NetStream
from .multiaddr import MultiAddr
from .connection.raw_connection import RawConnection

from peer.id import ID

class Swarm(INetwork):

    def __init__(self, my_peer_id, peerstore, upgrader):
        self._my_peer_id = my_peer_id
        self.id = ID(my_peer_id)
        self.peerstore = peerstore
        self.upgrader = upgrader
        self.connections = dict()
        self.listeners = dict()
        self.stream_handlers = dict()
        self.transport = None

    def get_peer_id(self):
        return self.id

    def set_stream_handler(self, protocol_id, stream_handler):
        """
        :param protocol_id: protocol id used on stream
        :param stream_handler: a stream handler instance
        :return: true if successful
        """
        self.stream_handlers[protocol_id] = stream_handler

    async def new_stream(self, peer_id, protocol_id):
        """
        :param peer_id: peer_id of destination
        :param protocol_id: protocol id
        :return: net stream instance
        """
        # Get peer info from peer store
        addrs = self.peerstore.addrs(peer_id)

        if not addrs:
            raise SwarmException("No known addresses to peer")

        multiaddr = addrs[0]

        if peer_id in self.connections:
            # If muxed connection already exists for peer_id,
            # set muxed connection equal to existing muxed connection
            muxed_conn = self.connections[peer_id]
        else:
            # Transport dials peer (gets back a raw conn)
            raw_conn = await self.transport.dial(MultiAddr(multiaddr))

            # Use upgrader to upgrade raw conn to muxed conn
            muxed_conn = self.upgrader.upgrade_connection(raw_conn, True)

            # Store muxed connection in connections
            self.connections[peer_id] = muxed_conn

        # Use muxed conn to open stream, which returns
        # a muxed stream
        # TODO: use better stream IDs
        stream_id = (uuid.uuid4().int & (1<<64)-1) >> 3
        muxed_stream = muxed_conn.open_stream(protocol_id, stream_id, peer_id, multiaddr)

        # Create a net stream
        net_stream = NetStream(muxed_stream)

        return net_stream

    async def listen(self, *args):
        """
        :param *args: one or many multiaddrs to start listening on
        :return: true if at least one success

        For each multiaddr in args
            Check if a listener for multiaddr exists already
            If listener already exists, continue
            Otherwise:
                Capture multiaddr in conn handler
                Have conn handler delegate to stream handler
                Call listener listen with the multiaddr
                Map multiaddr to listener
        """
        for multiaddr_str in args:
            if multiaddr_str in self.listeners:
                return True

            multiaddr = MultiAddr(multiaddr_str)
            multiaddr_dict = multiaddr.to_options()

            async def conn_handler(reader, writer):
                # Upgrade reader/write to a net_stream and pass \
                # to appropriate stream handler (using multiaddr)
                raw_conn = RawConnection(multiaddr_dict['host'], \
                    multiaddr_dict['port'], reader, writer)
                muxed_conn = self.upgrader.upgrade_connection(raw_conn, False)

                muxed_stream, stream_id, protocol_id = await muxed_conn.accept_stream()
                net_stream = NetStream(muxed_stream)
                net_stream.set_protocol(protocol_id)

                # Give to stream handler
                # TODO: handle case when stream handler is set
                # TODO: handle case of multiple protocols over same raw connection
                await self.stream_handlers[protocol_id](net_stream)

            try:
                # Success
                listener = self.transport.create_listener(conn_handler)
                self.listeners[multiaddr_str]  = listener
                await listener.listen(multiaddr)
                return True
            except IOError:
                # Failed. Continue looping.
                print("Failed to connect to: " + str(multiaddr))

        # No multiaddr succeeded
        return False

    def add_transport(self, transport):
        # TODO: Support more than one transport
        self.transport = transport

class SwarmException(Exception):
    pass
