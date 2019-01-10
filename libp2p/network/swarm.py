from libp2p.protocol_muxer.multiselect_client import MultiselectClient
from libp2p.protocol_muxer.multiselect import Multiselect


from .network_interface import INetwork
from .stream.net_stream import NetStream
from .connection.raw_connection import RawConnection


class Swarm(INetwork):
    # pylint: disable=too-many-instance-attributes, cell-var-from-loop

    def __init__(self, peer_id, peerstore, upgrader):
        self.self_id = peer_id
        self.peerstore = peerstore
        self.upgrader = upgrader
        self.connections = dict()
        self.listeners = dict()
        self.stream_handlers = dict()
        self.transport = None

        # Protocol muxing
        self.multiselect = Multiselect()
        self.multiselect_client = MultiselectClient()

    def get_peer_id(self):
        return self.self_id

    def set_stream_handler(self, protocol_id, stream_handler):
        """
        :param protocol_id: protocol id used on stream
        :param stream_handler: a stream handler instance
        :return: true if successful
        """
        self.multiselect.add_handler(protocol_id, stream_handler)
        return True

    async def dial_peer(self, peer_id):
        """
        dial_peer try to create a connection to peer_id
        :param peer_id: peer if we want to dial
        :raises SwarmException: raised when no address if found for peer_id
        :return: muxed connection
        """

        # Get peer info from peer store
        addrs = self.peerstore.addrs(peer_id)

        if not addrs:
            raise SwarmException("No known addresses to peer")

        # TODO: define logic to choose which address to use, or try them all ?
        multiaddr = addrs[0]

        if peer_id in self.connections:
            # If muxed connection already exists for peer_id,
            # set muxed connection equal to existing muxed connection
            muxed_conn = self.connections[peer_id]
        else:
            # Transport dials peer (gets back a raw conn)
            raw_conn = await self.transport.dial(multiaddr)

            # Use upgrader to upgrade raw conn to muxed conn
            muxed_conn = self.upgrader.upgrade_connection(raw_conn)

            # Store muxed connection in connections
            self.connections[peer_id] = muxed_conn

        return muxed_conn

    async def new_stream(self, peer_id, protocol_ids):
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

        muxed_conn = await self.dial_peer(peer_id)

        # Use muxed conn to open stream, which returns
        # a muxed stream
        # TODO: Remove protocol id from being passed into muxed_conn
        muxed_stream = await muxed_conn.open_stream(protocol_ids[0], peer_id, multiaddr)

        # Perform protocol muxing to determine protocol to use
        selected_protocol = await self.multiselect_client.select_one_of(protocol_ids, muxed_stream)

        # Create a net stream with the selected protocol
        net_stream = NetStream(muxed_stream)
        net_stream.set_protocol(selected_protocol)

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
        for multiaddr in args:
            if str(multiaddr) in self.listeners:
                return True

            async def conn_handler(reader, writer):
                # Upgrade reader/write to a net_stream and pass \
                # to appropriate stream handler (using multiaddr)
                raw_conn = RawConnection(multiaddr.value_for_protocol('ip4'),
                                         multiaddr.value_for_protocol('tcp'), reader, writer, False)
                muxed_conn = self.upgrader.upgrade_connection(raw_conn)

                # TODO: Remove protocol id from muxed_conn accept stream or
                # move protocol muxing into accept_stream
                muxed_stream, _, _ = await muxed_conn.accept_stream()

                # Perform protocol muxing to determine protocol to use
                selected_protocol, handler = await self.multiselect.negotiate(muxed_stream)

                net_stream = NetStream(muxed_stream)
                net_stream.set_protocol(selected_protocol)

                # Give to stream handler
                # TODO: handle case when stream handler is set
                # TODO: handle case of multiple protocols over same raw connection
                await handler(net_stream)

            try:
                # Success
                listener = self.transport.create_listener(conn_handler)
                self.listeners[str(multiaddr)] = listener
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
