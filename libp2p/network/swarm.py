import asyncio
from typing import Awaitable, Callable, Dict, List, Sequence

from multiaddr import Multiaddr

from libp2p.peer.id import ID
from libp2p.peer.peerstore import PeerStore
from libp2p.protocol_muxer.multiselect import Multiselect
from libp2p.protocol_muxer.multiselect_client import MultiselectClient
from libp2p.routing.interfaces import IPeerRouting
from libp2p.stream_muxer.muxed_connection_interface import IMuxedConn
from libp2p.stream_muxer.muxed_stream_interface import IMuxedStream
from libp2p.transport.upgrader import TransportUpgrader
from libp2p.transport.transport_interface import ITransport
from libp2p.transport.listener_interface import IListener


from .network_interface import INetwork
from .notifee_interface import INotifee
from .connection.raw_connection import RawConnection
from .stream.net_stream import NetStream
from .stream.net_stream_interface import INetStream


StreamHandlerFn = Callable[[INetStream], Awaitable[None]]


class Swarm(INetwork):

    self_id: ID
    peerstore: PeerStore
    upgrader: TransportUpgrader
    transport: ITransport
    router: IPeerRouting
    connections: Dict[ID, IMuxedConn]
    listeners: Dict[str, IListener]
    stream_handlers: Dict[INetStream, Callable[[INetStream], None]]

    multiselect: Multiselect
    multiselect_client: MultiselectClient

    notifees: List[INotifee]

    def __init__(
        self,
        peer_id: ID,
        peerstore: PeerStore,
        upgrader: TransportUpgrader,
        transport: ITransport,
        router: IPeerRouting,
    ):
        self.self_id = peer_id
        self.peerstore = peerstore
        self.upgrader = upgrader
        self.transport = transport
        self.router = router
        self.connections = dict()
        self.listeners = dict()
        self.stream_handlers = dict()

        # Protocol muxing
        self.multiselect = Multiselect()
        self.multiselect_client = MultiselectClient()

        # Create Notifee array
        self.notifees = []

        # Create generic protocol handler
        self.generic_protocol_handler = create_generic_protocol_handler(self)

    def get_peer_id(self) -> ID:
        return self.self_id

    def set_stream_handler(
        self, protocol_id: str, stream_handler: StreamHandlerFn
    ) -> bool:
        """
        :param protocol_id: protocol id used on stream
        :param stream_handler: a stream handler instance
        :return: true if successful
        """
        self.multiselect.add_handler(protocol_id, stream_handler)
        return True

    async def dial_peer(self, peer_id: ID) -> IMuxedConn:
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

        if not self.router:
            multiaddr = addrs[0]
        else:
            multiaddr = self.router.find_peer(peer_id)

        if peer_id in self.connections:
            # If muxed connection already exists for peer_id,
            # set muxed connection equal to existing muxed connection
            muxed_conn = self.connections[peer_id]
        else:
            # Dial peer (connection to peer does not yet exist)
            # Transport dials peer (gets back a raw conn)
            raw_conn = await self.transport.dial(multiaddr, self.self_id)

            # Per, https://discuss.libp2p.io/t/multistream-security/130, we first secure
            # the conn and then mux the conn
            secured_conn = await self.upgrader.upgrade_security(raw_conn, peer_id, True)
            muxed_conn = self.upgrader.upgrade_connection(
                secured_conn, self.generic_protocol_handler, peer_id
            )

            # Store muxed connection in connections
            self.connections[peer_id] = muxed_conn

            # Call notifiers since event occurred
            for notifee in self.notifees:
                await notifee.connected(self, muxed_conn)

        return muxed_conn

    async def new_stream(self, peer_id: ID, protocol_ids: Sequence[str]) -> NetStream:
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
        muxed_stream = await muxed_conn.open_stream(protocol_ids[0], multiaddr)

        # Perform protocol muxing to determine protocol to use
        selected_protocol = await self.multiselect_client.select_one_of(
            list(protocol_ids), muxed_stream
        )

        # Create a net stream with the selected protocol
        net_stream = NetStream(muxed_stream)
        net_stream.set_protocol(selected_protocol)

        # Call notifiers since event occurred
        for notifee in self.notifees:
            await notifee.opened_stream(self, net_stream)

        return net_stream

    async def listen(self, *multiaddrs: Sequence[Multiaddr]) -> bool:
        """
        :param multiaddrs: one or many multiaddrs to start listening on
        :return: true if at least one success

        For each multiaddr
            Check if a listener for multiaddr exists already
            If listener already exists, continue
            Otherwise:
                Capture multiaddr in conn handler
                Have conn handler delegate to stream handler
                Call listener listen with the multiaddr
                Map multiaddr to listener
        """
        for multiaddr in multiaddrs:
            if str(multiaddr) in self.listeners:
                return True

            async def conn_handler(
                reader: asyncio.StreamReader, writer: asyncio.StreamWriter
            ) -> None:
                # Read in first message (should be peer_id of initiator) and ack
                peer_id = ID.from_base58((await reader.read(1024)).decode())

                writer.write("received peer id".encode())
                await writer.drain()

                # Upgrade reader/write to a net_stream and pass \
                # to appropriate stream handler (using multiaddr)
                raw_conn = RawConnection(
                    multiaddr.value_for_protocol("ip4"),
                    multiaddr.value_for_protocol("tcp"),
                    reader,
                    writer,
                    False,
                )

                # Per, https://discuss.libp2p.io/t/multistream-security/130, we first secure
                # the conn and then mux the conn
                secured_conn = await self.upgrader.upgrade_security(
                    raw_conn, peer_id, False
                )
                muxed_conn = self.upgrader.upgrade_connection(
                    secured_conn, self.generic_protocol_handler, peer_id
                )

                # Store muxed_conn with peer id
                self.connections[peer_id] = muxed_conn

                # Call notifiers since event occurred
                for notifee in self.notifees:
                    await notifee.connected(self, muxed_conn)

            try:
                # Success
                listener = self.transport.create_listener(conn_handler)
                self.listeners[str(multiaddr)] = listener
                await listener.listen(multiaddr)

                # Call notifiers since event occurred
                for notifee in self.notifees:
                    await notifee.listen(self, multiaddr)

                return True
            except IOError:
                # Failed. Continue looping.
                print("Failed to connect to: " + str(multiaddr))

        # No multiaddr succeeded
        return False

    def notify(self, notifee: INotifee) -> bool:
        """
        :param notifee: object implementing Notifee interface
        :return: true if notifee registered successfully, false otherwise
        """
        if isinstance(notifee, INotifee):
            self.notifees.append(notifee)
            return True
        return False

    def add_router(self, router: IPeerRouting) -> None:
        self.router = router

    # TODO: `tear_down`
    async def tear_down(self) -> None:
        # Reference: https://github.com/libp2p/go-libp2p-swarm/blob/8be680aef8dea0a4497283f2f98470c2aeae6b65/swarm.go#L118  # noqa: E501
        pass

    # TODO: `disconnect`?


GenericProtocolHandlerFn = Callable[[IMuxedStream], Awaitable[None]]


def create_generic_protocol_handler(swarm: Swarm) -> GenericProtocolHandlerFn:
    """
    Create a generic protocol handler from the given swarm. We use swarm
    to extract the multiselect module so that generic_protocol_handler
    can use multiselect when generic_protocol_handler is called
    from a different class
    """
    multiselect = swarm.multiselect

    async def generic_protocol_handler(muxed_stream: IMuxedStream) -> None:
        # Perform protocol muxing to determine protocol to use
        protocol, handler = await multiselect.negotiate(muxed_stream)

        net_stream = NetStream(muxed_stream)
        net_stream.set_protocol(protocol)

        # Call notifiers since event occurred
        for notifee in swarm.notifees:
            await notifee.opened_stream(swarm, net_stream)

        # Give to stream handler
        asyncio.ensure_future(handler(net_stream))

    return generic_protocol_handler


class SwarmException(Exception):
    pass
