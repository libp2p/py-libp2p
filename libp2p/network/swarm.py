import asyncio
import logging
from typing import Dict, List, Optional, Sequence

from multiaddr import Multiaddr

from libp2p.network.connection.net_connection_interface import INetConn
from libp2p.peer.id import ID
from libp2p.peer.peerstore import PeerStoreError
from libp2p.peer.peerstore_interface import IPeerStore
from libp2p.routing.interfaces import IPeerRouting
from libp2p.stream_muxer.abc import IMuxedConn
from libp2p.transport.exceptions import MuxerUpgradeFailure, SecurityUpgradeFailure
from libp2p.transport.listener_interface import IListener
from libp2p.transport.transport_interface import ITransport
from libp2p.transport.upgrader import TransportUpgrader
from libp2p.typing import StreamHandlerFn, TProtocol

from .connection.raw_connection import RawConnection
from .connection.swarm_connection import SwarmConn
from .exceptions import SwarmException
from .network_interface import INetwork
from .notifee_interface import INotifee
from .stream.net_stream_interface import INetStream

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
    connections: Dict[ID, INetConn]
    listeners: Dict[str, IListener]
    common_stream_handler: Optional[StreamHandlerFn]

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

        # Create Notifee array
        self.notifees = []

        self.common_stream_handler = None

    def get_peer_id(self) -> ID:
        return self.self_id

    def set_stream_handler(self, stream_handler: StreamHandlerFn) -> None:
        self.common_stream_handler = stream_handler

    async def dial_peer(self, peer_id: ID) -> INetConn:
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
            error_msg = "fail to upgrade security for peer %s"
            logger.debug(error_msg, peer_id)
            await raw_conn.close()
            raise SwarmException(error_msg % peer_id) from error

        logger.debug("upgraded security for peer %s", peer_id)

        try:
            muxed_conn = await self.upgrader.upgrade_connection(secured_conn, peer_id)
        except MuxerUpgradeFailure as error:
            error_msg = "fail to upgrade mux for peer %s"
            logger.debug(error_msg, peer_id)
            await secured_conn.close()
            raise SwarmException(error_msg % peer_id) from error

        logger.debug("upgraded mux for peer %s", peer_id)

        swarm_conn = await self.add_conn(muxed_conn)

        logger.debug("successfully dialed peer %s", peer_id)

        return swarm_conn

    async def new_stream(
        self, peer_id: ID, protocol_ids: Sequence[TProtocol]
    ) -> INetStream:
        """
        :param peer_id: peer_id of destination
        :param protocol_id: protocol id
        :return: net stream instance
        """
        logger.debug(
            "attempting to open a stream to peer %s, over one of the protocols %s",
            peer_id,
            protocol_ids,
        )

        print(f"!@# swarm.new_stream: 0")
        swarm_conn = await self.dial_peer(peer_id)

        print(f"!@# swarm.new_stream: 1")
        net_stream = await swarm_conn.new_stream()
        logger.debug("successfully opened a stream to peer %s", peer_id)
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
                raw_conn = RawConnection(reader, writer, False)

                # Per, https://discuss.libp2p.io/t/multistream-security/130, we first secure
                # the conn and then mux the conn
                try:
                    # FIXME: This dummy `ID(b"")` for the remote peer is useless.
                    secured_conn = await self.upgrader.upgrade_security(
                        raw_conn, ID(b""), False
                    )
                except SecurityUpgradeFailure as error:
                    error_msg = "fail to upgrade security for peer at %s"
                    logger.debug(error_msg, peer_addr)
                    await raw_conn.close()
                    raise SwarmException(error_msg % peer_addr) from error
                peer_id = secured_conn.get_remote_peer()

                logger.debug("upgraded security for peer at %s", peer_addr)
                logger.debug("identified peer at %s as %s", peer_addr, peer_id)

                try:
                    muxed_conn = await self.upgrader.upgrade_connection(
                        secured_conn, peer_id
                    )
                except MuxerUpgradeFailure as error:
                    error_msg = "fail to upgrade mux for peer %s"
                    logger.debug(error_msg, peer_id)
                    await secured_conn.close()
                    raise SwarmException(error_msg % peer_id) from error
                logger.debug("upgraded mux for peer %s", peer_id)

                await self.add_conn(muxed_conn)

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
                logger.debug("fail to listen on: " + str(maddr))

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

        logger.debug("swarm successfully closed")

    async def close_peer(self, peer_id: ID) -> None:
        if peer_id not in self.connections:
            return
        connection = self.connections[peer_id]
        await connection.close()

        logger.debug("successfully close the connection to peer %s", peer_id)

    async def add_conn(self, muxed_conn: IMuxedConn) -> SwarmConn:
        swarm_conn = SwarmConn(muxed_conn, self)
        # Store muxed_conn with peer id
        self.connections[muxed_conn.peer_id] = swarm_conn
        # Call notifiers since event occurred
        for notifee in self.notifees:
            # TODO: Call with other type of conn?
            await notifee.connected(self, muxed_conn)
        await swarm_conn.start()
        return swarm_conn

    def remove_conn(self, swarm_conn: SwarmConn) -> None:
        print(f"!@# remove_conn: {swarm_conn}")
        peer_id = swarm_conn.conn.peer_id
        # TODO: Should be changed to remove the exact connection,
        #   if we have several connections per peer in the future.
        del self.connections[peer_id]
