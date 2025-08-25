from collections.abc import (
    Awaitable,
    Callable,
)
import logging

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
from libp2p.tools.async_service import (
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
    # Allow multiple connections per peer (list of INetConn)
    connections: dict[ID, list[INetConn]]
    listeners: dict[str, IListener]
    common_stream_handler: StreamHandlerFn
    listener_nursery: trio.Nursery | None
    event_listener_nursery_created: trio.Event
    notifees: list[INotifee]

    def __init__(
        self,
        peer_id: ID,
        peerstore: IPeerStore,
        upgrader: TransportUpgrader,
        transport: ITransport,
    ):
        self.self_id = peer_id
        self.peerstore = peerstore
        self.upgrader = upgrader
        self.transport = transport
        self.connections = dict()  # peer_id -> list of INetConn
        self.listeners = dict()
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

    async def dial_peer(self, peer_id: ID, max_retries: int = 3, base_delay: float = 0.5) -> INetConn:
        """
        Try to create a connection to peer_id with retry and exponential backoff.
        :param peer_id: peer if we want to dial
        :param max_retries: number of retry attempts
        :param base_delay: base delay for exponential backoff
        :raises SwarmException: raised when an error occurs
        :return: muxed connection
        """
        # If we already have a connection, return the first one
        if peer_id in self.connections and self.connections[peer_id]:
            return self.connections[peer_id][0]

        logger.info(f"Attempting to dial peer {peer_id}")
        attempt = 0
        exceptions: list[SwarmException] = []
        while attempt < max_retries:
            try:
                # Get peer info from peer store
                addrs = self.peerstore.addrs(peer_id)
            except PeerStoreError as error:
                logger.error(f"No known addresses to peer {peer_id}: {error}")
                raise SwarmException(f"No known addresses to peer {peer_id}") from error
            if not addrs:
                logger.error(f"No known addresses to peer {peer_id}")
                raise SwarmException(f"No known addresses to peer {peer_id}")
            for multiaddr in addrs:
                try:
                    conn = await self.dial_addr(multiaddr, peer_id)
                    # Store the connection
                    if peer_id not in self.connections:
                        self.connections[peer_id] = []
                    self.connections[peer_id].append(conn)
                    logger.info(f"Successfully connected to peer {peer_id} at {multiaddr}")
                    # Metrics: increment successful connection counter here
                    return conn
                except SwarmException as e:
                    exceptions.append(e)
                    logger.warning(
                        f"Attempt {attempt+1}: Failed to connect to {peer_id} at {multiaddr}: {e}"
                    )
            # Exponential backoff before retrying
            attempt += 1
            delay = base_delay * (2 ** (attempt - 1))
            logger.info(f"Retrying to dial peer {peer_id} after {delay:.2f}s (attempt {attempt+1})")
            await trio.sleep(delay)
        # All attempts failed
        logger.error(f"Unable to connect to {peer_id} after {max_retries} attempts")
        # Metrics: increment failed connection counter here
        raise SwarmException(
            f"unable to connect to {peer_id}, no addresses established a successful connection (with exceptions)"
        ) from MultiError(exceptions)

    async def dial_addr(self, addr: Multiaddr, peer_id: ID) -> INetConn:
        """
        Try to create a connection to peer_id with addr.

        :param addr: the address we want to connect with
        :param peer_id: the peer we want to connect to
        :raises SwarmException: raised when an error occurs
        :return: network connection
        """
        # Dial peer (connection to peer does not yet exist)
        # Transport dials peer (gets back a raw conn)
        try:
            raw_conn = await self.transport.dial(addr)
        except OpenConnectionError as error:
            logger.debug("fail to dial peer %s over base transport", peer_id)
            raise SwarmException(
                f"fail to open connection to peer {peer_id}"
            ) from error

        logger.debug("dialed peer %s over base transport", peer_id)

        # Per, https://discuss.libp2p.io/t/multistream-security/130, we first secure
        # the conn and then mux the conn
        try:
            secured_conn = await self.upgrader.upgrade_security(raw_conn, True, peer_id)
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
        """
        :param peer_id: peer_id of destination
        :raises SwarmException: raised when an error occurs
        :return: net stream instance
        """
        logger.debug("attempting to open a stream to peer %s", peer_id)

        swarm_conn = await self.dial_peer(peer_id)

        net_stream = await swarm_conn.new_stream()
        logger.debug("successfully opened a stream to peer %s", peer_id)
        return net_stream

    async def listen(self, *multiaddrs: Multiaddr) -> bool:
        """
        :param multiaddrs: one or many multiaddrs to start listening on
        :return: true if at least one success

        For each multiaddr

          - Check if a listener for multiaddr exists already
          - If listener already exists, continue
          - Otherwise:

              - Capture multiaddr in conn handler
              - Have conn handler delegate to stream handler
              - Call listener listen with the multiaddr
              - Map multiaddr to listener
        """
        # We need to wait until `self.listener_nursery` is created.
        await self.event_listener_nursery_created.wait()

        success_count = 0
        for maddr in multiaddrs:
            if str(maddr) in self.listeners:
                success_count += 1
                continue

            async def conn_handler(
                read_write_closer: ReadWriteCloser, maddr: Multiaddr = maddr
            ) -> None:
                raw_conn = RawConnection(read_write_closer, False)

                # Per, https://discuss.libp2p.io/t/multistream-security/130, we first
                # secure the conn and then mux the conn
                try:
                    secured_conn = await self.upgrader.upgrade_security(raw_conn, False)
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

                # NOTE: This is a intentional barrier to prevent from the handler
                # exiting and closing the connection.
                await self.manager.wait_finished()

            try:
                # Success
                listener = self.transport.create_listener(conn_handler)
                self.listeners[str(maddr)] = listener
                # TODO: `listener.listen` is not bounded with nursery. If we want to be
                #   I/O agnostic, we should change the API.
                if self.listener_nursery is None:
                    raise SwarmException("swarm instance hasn't been run")
                await listener.listen(maddr, self.listener_nursery)

                # Call notifiers since event occurred
                await self.notify_listen(maddr)

                success_count += 1
                logger.debug("successfully started listening on: %s", maddr)
            except OSError:
                # Failed. Continue looping.
                logger.debug("fail to listen on: %s", maddr)

        # Return true if at least one address succeeded
        return success_count > 0

    async def close(self) -> None:
        """
        Close the swarm instance and cleanup resources.
        """
        # Check if manager exists before trying to stop it
        if hasattr(self, "_manager") and self._manager is not None:
            await self._manager.stop()
        else:
            # Perform alternative cleanup if the manager isn't initialized
            # Close all connections manually
            if hasattr(self, "connections"):
                for conn_id in list(self.connections.keys()):
                    for conn in self.connections[conn_id]:
                        await conn.close()

                # Clear connection tracking dictionary
                self.connections.clear()

            # Close all listeners
            if hasattr(self, "listeners"):
                for maddr_str, listener in self.listeners.items():
                    await listener.close()
                    # Notify about listener closure
                    try:
                        multiaddr = Multiaddr(maddr_str)
                        await self.notify_listen_close(multiaddr)
                    except Exception as e:
                        logger.warning(
                            f"Failed to notify listen_close for {maddr_str}: {e}"
                        )
                self.listeners.clear()

            # Close the transport if it exists and has a close method
            if hasattr(self, "transport") and self.transport is not None:
                # Check if transport has close method before calling it
                if hasattr(self.transport, "close"):
                    await self.transport.close()  # type: ignore
                # Ignoring the type above since `transport` may not have a close method
                # and we have already checked it with hasattr

        logger.debug("swarm successfully closed")

    async def close_peer(self, peer_id: ID) -> None:
        if peer_id not in self.connections:
            return
        for conn in self.connections[peer_id]:
            # NOTE: `conn.close` will delete `peer_id` from `self.connections`
            # and `notify_disconnected` for us.
            await conn.close()

        logger.debug("successfully close the connection to peer %s", peer_id)

    async def add_conn(self, muxed_conn: IMuxedConn) -> SwarmConn:
        """
        Add a `IMuxedConn` to `Swarm` as a `SwarmConn`, notify "connected",
        and start to monitor the connection for its new streams and
        disconnection.
        """
        swarm_conn = SwarmConn(
            muxed_conn,
            self,
        )

        self.manager.run_task(muxed_conn.start)
        await muxed_conn.event_started.wait()
        self.manager.run_task(swarm_conn.start)
        await swarm_conn.event_started.wait()
        # Store muxed_conn with peer id
        if muxed_conn.peer_id not in self.connections:
            self.connections[muxed_conn.peer_id] = []
        self.connections[muxed_conn.peer_id].append(swarm_conn)
        # Call notifiers since event occurred
        await self.notify_connected(swarm_conn)
        return swarm_conn

    def remove_conn(self, swarm_conn: SwarmConn) -> None:
        """
        Simply remove the connection from Swarm's records, without closing
        the connection.
        """
        peer_id = swarm_conn.muxed_conn.peer_id
        if peer_id not in self.connections:
            return
        self.connections[peer_id].remove(swarm_conn)

    # Notifee

    def register_notifee(self, notifee: INotifee) -> None:
        """
        :param notifee: object implementing Notifee interface
        :return: true if notifee registered successfully, false otherwise
        """
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
        async with trio.open_nursery() as nursery:
            for notifee in self.notifees:
                nursery.start_soon(notifee.closed_stream, self, stream)

    async def notify_listen_close(self, multiaddr: Multiaddr) -> None:
        async with trio.open_nursery() as nursery:
            for notifee in self.notifees:
                nursery.start_soon(notifee.listen_close, self, multiaddr)

    # Generic notifier used by NetStream._notify_closed
    async def notify_all(self, notifier: Callable[[INotifee], Awaitable[None]]) -> None:
        async with trio.open_nursery() as nursery:
            for notifee in self.notifees:
                nursery.start_soon(notifier, notifee)
