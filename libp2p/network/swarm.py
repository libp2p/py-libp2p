# libp2p/network/swarm.py
import logging
from typing import (
    Optional,
)

from multiaddr import (
    Multiaddr,
)
import trio

from libp2p.abc import (
    IListener,
    IMuxedConn,
    INetConn,
    INetStream,
    INetworkService,
    INotifee,
    IPeerStore,
    ITransport,
)
from libp2p.custom_types import (
    StreamHandlerFn,
)
from libp2p.io.abc import (
    ReadWriteCloser,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.peer.peerstore import (
    PeerStoreError,
)
from libp2p.tools.anyio_service import (
    Service,
)
from libp2p.transport.exceptions import (
    MuxerUpgradeFailure,
    OpenConnectionError,
    SecurityUpgradeFailure,
)
from libp2p.transport.upgrader import (
    TransportUpgrader,
)

from ..exceptions import (
    MultiError,
)
from .connection.raw_connection import (
    RawConnection,
)
from .connection.swarm_connection import (
    SwarmConn,
)
from .exceptions import (
    SwarmException,
)

logger = logging.getLogger("libp2p.network.swarm")


def create_default_stream_handler(network: INetworkService) -> StreamHandlerFn:
    async def stream_handler(stream: INetStream) -> None:
        await network.get_manager().wait_finished()

    return stream_handler


class Swarm(Service, INetworkService):
    self_id: ID
    peerstore: IPeerStore
    upgrader: TransportUpgrader
    transport: ITransport
    connections: dict[ID, INetConn]
    listeners: dict[str, IListener]
    common_stream_handler: StreamHandlerFn
    listener_nursery: Optional[trio.Nursery]
    event_listener_nursery_created: trio.Event
    notifees: list[INotifee]

    def __init__(
        self,
        peer_id: ID,
        peerstore: IPeerStore,
        upgrader: TransportUpgrader,
        transport: ITransport,
    ):
        super().__init__()  # Initialize Service to set _manager
        self.self_id = peer_id
        self.peerstore = peerstore
        self.upgrader = upgrader
        self.transport = transport
        self.connections = dict()
        self.listeners = dict()

        # Create Notifee array
        self.notifees = []

        self.common_stream_handler = create_default_stream_handler(self)

        self.listener_nursery = None
        self.event_listener_nursery_created = trio.Event()

    async def run(self) -> None:
        async with trio.open_nursery() as nursery:
            # Create a nursery for listener tasks.
            self.listener_nursery = nursery
            self.event_listener_nursery_created.set()
            try:
                await self.manager.wait_finished()
            finally:
                # The service ended. Cancel listener tasks.
                nursery.cancel_scope.cancel()
                # Indicate that the nursery has been cancelled.
                self.listener_nursery = None

    def get_peer_id(self) -> ID:
        return self.self_id

    def set_stream_handler(self, stream_handler: StreamHandlerFn) -> None:
        self.common_stream_handler = stream_handler

    async def dial_peer(self, peer_id: ID) -> INetConn:
        if peer_id in self.connections:
            return self.connections[peer_id]

        logger.debug("attempting to dial peer %s", peer_id)

        try:
            addrs = self.peerstore.addrs(peer_id)
        except PeerStoreError as error:
            raise SwarmException(f"No known addresses to peer {peer_id}") from error

        if not addrs:
            raise SwarmException(f"No known addresses to peer {peer_id}")

        exceptions: list[SwarmException] = []

        for multiaddr in addrs:
            try:
                return await self.dial_addr(multiaddr, peer_id)
            except SwarmException as e:
                exceptions.append(e)
                logger.debug(
                    "encountered swarm exception when trying to connect to %s, "
                    "trying next address...",
                    multiaddr,
                    exc_info=e,
                )

        raise SwarmException(
            f"unable to connect to {peer_id}, no addresses established a successful "
            "connection (with exceptions)"
        ) from MultiError(exceptions)

    async def dial_addr(self, addr: Multiaddr, peer_id: ID) -> INetConn:
        try:
            raw_conn = await self.transport.dial(addr)
        except OpenConnectionError as error:
            logger.debug("fail to dial peer %s over base transport", peer_id)
            raise SwarmException(
                f"fail to open connection to peer {peer_id}"
            ) from error

        logger.debug("dialed peer %s over base transport", peer_id)

        try:
            secured_conn = await self.upgrader.upgrade_security(raw_conn, peer_id, True)
        except SecurityUpgradeFailure as error:
            logger.debug("failed to upgrade security for peer %s", peer_id)
            await raw_conn.close()
            raise SwarmException(
                f"failed to upgrade security for peer {peer_id}"
            ) from error

        logger.debug("upgraded security for peer %s", peer_id)

        try:
            muxed_conn = await self.upgrader.upgrade_connection(secured_conn, peer_id)
        except MuxerUpgradeFailure as error:
            logger.debug("failed to upgrade mux for peer %s", peer_id)
            await secured_conn.close()
            raise SwarmException(f"failed to upgrade mux for peer {peer_id}") from error

        logger.debug("upgraded mux for peer %s", peer_id)

        swarm_conn = await self.add_conn(muxed_conn)

        logger.debug("successfully dialed peer %s", peer_id)

        return swarm_conn

    async def new_stream(self, peer_id: ID) -> INetStream:
        logger.debug("attempting to open a stream to peer %s", peer_id)

        swarm_conn = await self.dial_peer(peer_id)

        net_stream = await swarm_conn.new_stream()
        logger.debug("successfully opened a stream to peer %s", peer_id)
        return net_stream

    async def listen(self, *multiaddrs: Multiaddr) -> bool:
        await self.event_listener_nursery_created.wait()

        for maddr in multiaddrs:
            if str(maddr) in self.listeners:
                return True

            async def conn_handler(
                read_write_closer: ReadWriteCloser, maddr: Multiaddr = maddr
            ) -> None:
                raw_conn = RawConnection(read_write_closer, False)

                try:
                    secured_conn = await self.upgrader.upgrade_security(
                        raw_conn, ID(b""), False
                    )
                except SecurityUpgradeFailure as error:
                    logger.debug("failed to upgrade security for peer at %s", maddr)
                    await raw_conn.close()
                    raise SwarmException(
                        f"failed to upgrade security for peer at {maddr}"
                    ) from error
                peer_id = secured_conn.get_remote_peer()

                try:
                    muxed_conn = await self.upgrader.upgrade_connection(
                        secured_conn, peer_id
                    )
                except MuxerUpgradeFailure as error:
                    logger.debug("fail to upgrade mux for peer %s", peer_id)
                    await secured_conn.close()
                    raise SwarmException(
                        f"fail to upgrade mux for peer {peer_id}"
                    ) from error
                logger.debug("upgraded mux for peer %s", peer_id)

                await self.add_conn(muxed_conn)
                logger.debug("successfully opened connection to peer %s", peer_id)

                await self.manager.wait_finished()

            try:
                listener = self.transport.create_listener(conn_handler)
                self.listeners[str(maddr)] = listener
                if self.listener_nursery is None:
                    raise SwarmException("swarm instance hasn't been run")
                await listener.listen(maddr, self.listener_nursery)

                await self.notify_listen(maddr)

                return True
            except OSError:
                logger.debug("fail to listen on: %s", maddr)

        return False

    async def close(self) -> None:
        await self.manager.stop()
        logger.debug("swarm successfully closed")

    async def close_peer(self, peer_id: ID) -> None:
        if peer_id not in self.connections:
            return
        connection = self.connections[peer_id]
        await connection.close()

        logger.debug("successfully close the connection to peer %s", peer_id)

    async def add_conn(self, muxed_conn: IMuxedConn) -> SwarmConn:
        swarm_conn = SwarmConn(muxed_conn, self)
        self.manager.run_task(muxed_conn.start)
        await muxed_conn.event_started.wait()
        self.manager.run_task(swarm_conn.start)
        await swarm_conn.event_started.wait()
        self.connections[muxed_conn.peer_id] = swarm_conn
        await self.notify_connected(swarm_conn)
        return swarm_conn

    def remove_conn(self, swarm_conn: SwarmConn) -> None:
        peer_id = swarm_conn.muxed_conn.peer_id
        if peer_id not in self.connections:
            return
        del self.connections[peer_id]

    # Notifee methods
    def register_notifee(self, notifee: INotifee) -> None:
        self.notifees.append(notifee)

    async def notify_opened_stream(self, stream: INetStream) -> None:
        async with trio.open_nursery() as nursery:
            for notifee in self.notifees:
                nursery.start_soon(notifee.opened_stream, self, stream)

    async def notify_connected(self, conn: INetConn) -> None:
        async with trio.open_nursery() as nursery:
            for notifee in self.notifees:
                nursery.start_soon(notifee.connected, self, conn)

    async def notify_disconnected(self, conn: INetConn) -> None:
        async with trio.open_nursery() as nursery:
            for notifee in self.notifees:
                nursery.start_soon(notifee.disconnected, self, conn)

    async def notify_listen(self, multiaddr: Multiaddr) -> None:
        async with trio.open_nursery() as nursery:
            for notifee in self.notifees:
                nursery.start_soon(notifee.listen, self, multiaddr)

    async def notify_closed_stream(self, stream: INetStream) -> None:
        raise NotImplementedError

    async def notify_listen_close(self, multiaddr: Multiaddr) -> None:
        raise NotImplementedError
