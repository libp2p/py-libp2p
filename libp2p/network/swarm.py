import asyncio
import logging
from typing import Callable, Dict, List, Sequence

from multiaddr import Multiaddr

from libp2p.peer.id import ID
from libp2p.peer.peerstore import PeerStoreError
from libp2p.peer.peerstore_interface import IPeerStore
from libp2p.protocol_muxer.multiselect import Multiselect
from libp2p.protocol_muxer.multiselect_client import MultiselectClient
from libp2p.protocol_muxer.multiselect_communicator import MultiselectCommunicator
from libp2p.routing.interfaces import IPeerRouting
from libp2p.stream_muxer.abc import IMuxedConn, IMuxedStream
from libp2p.transport.exceptions import MuxerUpgradeFailure, SecurityUpgradeFailure
from libp2p.transport.listener_interface import IListener
from libp2p.transport.transport_interface import ITransport
from libp2p.transport.upgrader import TransportUpgrader
from libp2p.typing import StreamHandlerFn, TProtocol

from .connection.raw_connection import RawConnection
from .exceptions import SwarmException
from .network_interface import INetwork
from .notifee_interface import INotifee
from .stream.net_stream import NetStream
from .stream.net_stream_interface import INetStream
from .typing import GenericProtocolHandlerFn

logger = logging.getLogger("libp2p.network.swarm")
logger.setLevel(logging.DEBUG)


class Swarm(INetwork):

    self_id: ID
    peerstore: IPeerStore
    upgrader: TransportUpgrader
    transport: ITransport
    router: IPeerRouting
    # TODO: Connection and `peer_id` are 1-1 mapping in our implementation,
    #   whereas in Go one `peer_id` may point to multiple connections.
    connections: Dict[ID, IMuxedConn]
    listeners: Dict[str, IListener]
    stream_handlers: Dict[INetStream, Callable[[INetStream], None]]

    multiselect: Multiselect
    multiselect_client: MultiselectClient

    notifees: List[INotifee]

    def __init__(
        self,
        peer_id: ID,
        peerstore: IPeerStore,
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
        self, protocol_id: TProtocol, stream_handler: StreamHandlerFn
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
        :raises SwarmException: raised when an error occurs
        :return: muxed connection
        """

        if peer_id in self.connections:
            # If muxed connection already exists for peer_id,
            # set muxed connection equal to existing muxed connection
            return self.connections[peer_id]

        logger.debug("attempting to dial peer %s", peer_id)

        try:
            # Get peer info from peer store
            addrs = self.peerstore.addrs(peer_id)
        except PeerStoreError:
            raise SwarmException(f"No known addresses to peer {peer_id}")

        if not addrs:
            raise SwarmException(f"No known addresses to peer {peer_id}")

        if not self.router:
            multiaddr = addrs[0]
        else:
            multiaddr = self.router.find_peer(peer_id)
        # Dial peer (connection to peer does not yet exist)
        # Transport dials peer (gets back a raw conn)
        raw_conn = await self.transport.dial(multiaddr)

        logger.debug("dialed peer %s over base transport", peer_id)

        # Per, https://discuss.libp2p.io/t/multistream-security/130, we first secure
        # the conn and then mux the conn
        try:
            secured_conn = await self.upgrader.upgrade_security(raw_conn, peer_id, True)
        except SecurityUpgradeFailure as error:
            # TODO: Add logging to indicate the failure
            await raw_conn.close()
            raise SwarmException(
                f"fail to upgrade the connection to a secured connection from {peer_id}"
            ) from error

        logger.debug("upgraded security for peer %s", peer_id)

        try:
            muxed_conn = await self.upgrader.upgrade_connection(
                secured_conn, self.generic_protocol_handler, peer_id
            )
        except MuxerUpgradeFailure as error:
            # TODO: Add logging to indicate the failure
            await secured_conn.close()
            raise SwarmException(
                f"fail to upgrade the connection to a muxed connection from {peer_id}"
            ) from error

        logger.debug("upgraded mux for peer %s", peer_id)

        # Store muxed connection in connections
        self.connections[peer_id] = muxed_conn

        # Call notifiers since event occurred
        for notifee in self.notifees:
            await notifee.connected(self, muxed_conn)

        logger.debug("successfully dialed peer %s", peer_id)

        return muxed_conn

    async def new_stream(
        self, peer_id: ID, protocol_ids: Sequence[TProtocol]
    ) -> NetStream:
        """
        :param peer_id: peer_id of destination
        :param protocol_id: protocol id
        :return: net stream instance
        """

        muxed_conn = await self.dial_peer(peer_id)

        # Use muxed conn to open stream, which returns a muxed stream
        muxed_stream = await muxed_conn.open_stream()

        # Perform protocol muxing to determine protocol to use
        selected_protocol = await self.multiselect_client.select_one_of(
            list(protocol_ids), MultiselectCommunicator(muxed_stream)
        )

        # Create a net stream with the selected protocol
        net_stream = NetStream(muxed_stream)
        net_stream.set_protocol(selected_protocol)

        # Call notifiers since event occurred
        for notifee in self.notifees:
            await notifee.opened_stream(self, net_stream)

        return net_stream

    async def listen(self, *multiaddrs: Multiaddr) -> bool:
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
        for maddr in multiaddrs:
            if str(maddr) in self.listeners:
                return True

            async def conn_handler(
                reader: asyncio.StreamReader, writer: asyncio.StreamWriter
            ) -> None:
                connection_info = writer.get_extra_info("peername")
                # TODO make a proper multiaddr
                peer_addr = f"/ip4/{connection_info[0]}/tcp/{connection_info[1]}"
                logger.debug("inbound connection at %s", peer_addr)
                # logger.debug("inbound connection request", peer_id)
                # Upgrade reader/write to a net_stream and pass \
                # to appropriate stream handler (using multiaddr)
                raw_conn = RawConnection(reader, writer, False)

                # Per, https://discuss.libp2p.io/t/multistream-security/130, we first secure
                # the conn and then mux the conn
                try:
                    # FIXME: This dummy `ID(b"")` for the remote peer is useless.
                    secured_conn = await self.upgrader.upgrade_security(
                        raw_conn, ID(b""), False
                    )
                except SecurityUpgradeFailure as error:
                    # TODO: Add logging to indicate the failure
                    await raw_conn.close()
                    raise SwarmException(
                        "fail to upgrade the connection to a secured connection"
                    ) from error
                peer_id = secured_conn.get_remote_peer()

                logger.debug("upgraded security for peer at %s", peer_addr)
                logger.debug("identified peer at %s as %s", peer_addr, peer_id)

                try:
                    muxed_conn = await self.upgrader.upgrade_connection(
                        secured_conn, self.generic_protocol_handler, peer_id
                    )
                except MuxerUpgradeFailure as error:
                    # TODO: Add logging to indicate the failure
                    await secured_conn.close()
                    raise SwarmException(
                        f"fail to upgrade the connection to a muxed connection from {peer_id}"
                    ) from error
                logger.debug("upgraded mux for peer %s", peer_id)
                # Store muxed_conn with peer id
                self.connections[peer_id] = muxed_conn
                # Call notifiers since event occurred
                for notifee in self.notifees:
                    await notifee.connected(self, muxed_conn)

                logger.debug("successfully opened connection to peer %s", peer_id)

            try:
                # Success
                listener = self.transport.create_listener(conn_handler)
                self.listeners[str(maddr)] = listener
                await listener.listen(maddr)

                # Call notifiers since event occurred
                for notifee in self.notifees:
                    await notifee.listen(self, maddr)

                return True
            except IOError:
                # Failed. Continue looping.
                print("Failed to connect to: " + str(maddr))

        # No maddr succeeded
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

    async def close(self) -> None:
        # TODO: Prevent from new listeners and conns being added.
        #   Reference: https://github.com/libp2p/go-libp2p-swarm/blob/8be680aef8dea0a4497283f2f98470c2aeae6b65/swarm.go#L124-L134  # noqa: E501

        # Close listeners
        await asyncio.gather(
            *[listener.close() for listener in self.listeners.values()]
        )

        # Close connections
        await asyncio.gather(
            *[connection.close() for connection in self.connections.values()]
        )

    async def close_peer(self, peer_id: ID) -> None:
        if peer_id not in self.connections:
            return
        connection = self.connections[peer_id]
        del self.connections[peer_id]
        await connection.close()


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
        protocol, handler = await multiselect.negotiate(
            MultiselectCommunicator(muxed_stream)
        )

        net_stream = NetStream(muxed_stream)
        net_stream.set_protocol(protocol)

        # Call notifiers since event occurred
        for notifee in swarm.notifees:
            await notifee.opened_stream(swarm, net_stream)

        # Give to stream handler
        asyncio.ensure_future(handler(net_stream))

    return generic_protocol_handler
