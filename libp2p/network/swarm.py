from collections.abc import (
    Awaitable,
    Callable,
)
from dataclasses import dataclass
import logging
import random

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


@dataclass
class RetryConfig:
    """Configuration for retry logic with exponential backoff."""

    max_retries: int = 3
    initial_delay: float = 0.1
    max_delay: float = 30.0
    backoff_multiplier: float = 2.0
    jitter_factor: float = 0.1


@dataclass
class ConnectionConfig:
    """Configuration for connection pool and multi-connection support."""

    max_connections_per_peer: int = 3
    connection_timeout: float = 30.0
    enable_connection_pool: bool = True
    load_balancing_strategy: str = "round_robin"  # or "least_loaded"


@dataclass
class ConnectionInfo:
    """Information about a connection in the pool."""

    connection: INetConn
    address: str
    established_at: float
    last_used: float
    stream_count: int
    is_healthy: bool


class ConnectionPool:
    """Manages multiple connections per peer with load balancing."""

    def __init__(self, max_connections_per_peer: int = 3):
        self.max_connections_per_peer = max_connections_per_peer
        self.peer_connections: dict[ID, list[ConnectionInfo]] = {}
        self._round_robin_index: dict[ID, int] = {}

    def add_connection(self, peer_id: ID, connection: INetConn, address: str) -> None:
        """Add a connection to the pool with deduplication."""
        if peer_id not in self.peer_connections:
            self.peer_connections[peer_id] = []

        # Check for duplicate connections to the same address
        for conn_info in self.peer_connections[peer_id]:
            if conn_info.address == address:
                logger.debug(
                    f"Connection to {address} already exists for peer {peer_id}"
                )
                return

        # Add new connection
        try:
            current_time = trio.current_time()
        except RuntimeError:
            # Fallback for testing contexts where trio is not running
            import time

            current_time = time.time()

        conn_info = ConnectionInfo(
            connection=connection,
            address=address,
            established_at=current_time,
            last_used=current_time,
            stream_count=0,
            is_healthy=True,
        )

        self.peer_connections[peer_id].append(conn_info)

        # Trim if we exceed max connections
        if len(self.peer_connections[peer_id]) > self.max_connections_per_peer:
            self._trim_connections(peer_id)

    def get_connection(
        self, peer_id: ID, strategy: str = "round_robin"
    ) -> INetConn | None:
        """Get a connection using the specified load balancing strategy."""
        if peer_id not in self.peer_connections or not self.peer_connections[peer_id]:
            return None

        connections = self.peer_connections[peer_id]

        if strategy == "round_robin":
            if peer_id not in self._round_robin_index:
                self._round_robin_index[peer_id] = 0

            index = self._round_robin_index[peer_id] % len(connections)
            self._round_robin_index[peer_id] += 1

            conn_info = connections[index]
            try:
                conn_info.last_used = trio.current_time()
            except RuntimeError:
                import time

                conn_info.last_used = time.time()
            return conn_info.connection

        elif strategy == "least_loaded":
            # Find connection with least streams
            # Note: stream_count is a custom attribute we add to connections
            conn_info = min(
                connections, key=lambda c: getattr(c.connection, "stream_count", 0)
            )
            try:
                conn_info.last_used = trio.current_time()
            except RuntimeError:
                import time

                conn_info.last_used = time.time()
            return conn_info.connection

        else:
            # Default to first connection
            conn_info = connections[0]
            try:
                conn_info.last_used = trio.current_time()
            except RuntimeError:
                import time

                conn_info.last_used = time.time()
            return conn_info.connection

    def has_connection(self, peer_id: ID) -> bool:
        """Check if we have any connections to the peer."""
        return (
            peer_id in self.peer_connections and len(self.peer_connections[peer_id]) > 0
        )

    def remove_connection(self, peer_id: ID, connection: INetConn) -> None:
        """Remove a connection from the pool."""
        if peer_id in self.peer_connections:
            self.peer_connections[peer_id] = [
                conn_info
                for conn_info in self.peer_connections[peer_id]
                if conn_info.connection != connection
            ]

            # Clean up empty peer entries
            if not self.peer_connections[peer_id]:
                del self.peer_connections[peer_id]
                if peer_id in self._round_robin_index:
                    del self._round_robin_index[peer_id]

    def _trim_connections(self, peer_id: ID) -> None:
        """Remove oldest connections when limit is exceeded."""
        connections = self.peer_connections[peer_id]
        if len(connections) <= self.max_connections_per_peer:
            return

        # Sort by last used time and remove oldest
        connections.sort(key=lambda c: c.last_used)
        connections_to_remove = connections[: -self.max_connections_per_peer]

        for conn_info in connections_to_remove:
            logger.debug(
                f"Trimming old connection to {conn_info.address} for peer {peer_id}"
            )
            try:
                # Close the connection asynchronously
                trio.lowlevel.spawn_system_task(
                    self._close_connection_async, conn_info.connection
                )
            except Exception as e:
                logger.warning(f"Error closing trimmed connection: {e}")

        # Keep only the most recently used connections
        self.peer_connections[peer_id] = connections[-self.max_connections_per_peer :]

    async def _close_connection_async(self, connection: INetConn) -> None:
        """Close a connection asynchronously."""
        try:
            await connection.close()
        except Exception as e:
            logger.warning(f"Error closing connection: {e}")


def create_default_stream_handler(network: INetworkService) -> StreamHandlerFn:
    async def stream_handler(stream: INetStream) -> None:
        await network.get_manager().wait_finished()

    return stream_handler


class Swarm(Service, INetworkService):
    self_id: ID
    peerstore: IPeerStore
    upgrader: TransportUpgrader
    transport: ITransport
    # Enhanced: Support for multiple connections per peer
    connections: dict[ID, INetConn]  # Backward compatibility
    listeners: dict[str, IListener]
    common_stream_handler: StreamHandlerFn
    listener_nursery: trio.Nursery | None
    event_listener_nursery_created: trio.Event

    notifees: list[INotifee]

    # Enhanced: New configuration and connection pool
    retry_config: RetryConfig
    connection_config: ConnectionConfig
    connection_pool: ConnectionPool | None

    def __init__(
        self,
        peer_id: ID,
        peerstore: IPeerStore,
        upgrader: TransportUpgrader,
        transport: ITransport,
        retry_config: RetryConfig | None = None,
        connection_config: ConnectionConfig | None = None,
    ):
        self.self_id = peer_id
        self.peerstore = peerstore
        self.upgrader = upgrader
        self.transport = transport

        # Enhanced: Initialize retry and connection configuration
        self.retry_config = retry_config or RetryConfig()
        self.connection_config = connection_config or ConnectionConfig()

        # Enhanced: Initialize connection pool if enabled
        if self.connection_config.enable_connection_pool:
            self.connection_pool = ConnectionPool(
                self.connection_config.max_connections_per_peer
            )
        else:
            self.connection_pool = None

        # Backward compatibility: Keep existing connections dict
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
        """
        Try to create a connection to peer_id with enhanced retry logic.

        :param peer_id: peer if we want to dial
        :raises SwarmException: raised when an error occurs
        :return: muxed connection
        """
        # Enhanced: Check connection pool first if enabled
        if self.connection_pool and self.connection_pool.has_connection(peer_id):
            connection = self.connection_pool.get_connection(peer_id)
            if connection:
                logger.debug(f"Reusing existing connection to peer {peer_id}")
                return connection

        # Enhanced: Check existing single connection for backward compatibility
        if peer_id in self.connections:
            # If muxed connection already exists for peer_id,
            # set muxed connection equal to existing muxed connection
            return self.connections[peer_id]

        logger.debug("attempting to dial peer %s", peer_id)

        try:
            # Get peer info from peer store
            addrs = self.peerstore.addrs(peer_id)
        except PeerStoreError as error:
            raise SwarmException(f"No known addresses to peer {peer_id}") from error

        if not addrs:
            raise SwarmException(f"No known addresses to peer {peer_id}")

        exceptions: list[SwarmException] = []

        # Enhanced: Try all known addresses with retry logic
        for multiaddr in addrs:
            try:
                connection = await self._dial_with_retry(multiaddr, peer_id)

                # Enhanced: Add to connection pool if enabled
                if self.connection_pool:
                    self.connection_pool.add_connection(
                        peer_id, connection, str(multiaddr)
                    )

                # Backward compatibility: Keep existing connections dict
                self.connections[peer_id] = connection

                return connection
            except SwarmException as e:
                exceptions.append(e)
                logger.debug(
                    "encountered swarm exception when trying to connect to %s, "
                    "trying next address...",
                    multiaddr,
                    exc_info=e,
                )

        # Tried all addresses, raising exception.
        raise SwarmException(
            f"unable to connect to {peer_id}, no addresses established a successful "
            "connection (with exceptions)"
        ) from MultiError(exceptions)

    async def _dial_with_retry(self, addr: Multiaddr, peer_id: ID) -> INetConn:
        """
        Enhanced: Dial with retry logic and exponential backoff.

        :param addr: the address to dial
        :param peer_id: the peer we want to connect to
        :raises SwarmException: raised when all retry attempts fail
        :return: network connection
        """
        last_exception = None

        for attempt in range(self.retry_config.max_retries + 1):
            try:
                return await self._dial_addr_single_attempt(addr, peer_id)
            except Exception as e:
                last_exception = e
                if attempt < self.retry_config.max_retries:
                    delay = self._calculate_backoff_delay(attempt)
                    logger.debug(
                        f"Connection attempt {attempt + 1} failed, "
                        f"retrying in {delay:.2f}s: {e}"
                    )
                    await trio.sleep(delay)
                else:
                    logger.debug(f"All {self.retry_config.max_retries} attempts failed")

        # Convert the last exception to SwarmException for consistency
        if last_exception is not None:
            if isinstance(last_exception, SwarmException):
                raise last_exception
            else:
                raise SwarmException(
                    f"Failed to connect after {self.retry_config.max_retries} attempts"
                ) from last_exception

        # This should never be reached, but mypy requires it
        raise SwarmException("Unexpected error in retry logic")

    def _calculate_backoff_delay(self, attempt: int) -> float:
        """
        Enhanced: Calculate backoff delay with jitter to prevent thundering herd.

        :param attempt: the current attempt number (0-based)
        :return: delay in seconds
        """
        delay = min(
            self.retry_config.initial_delay
            * (self.retry_config.backoff_multiplier**attempt),
            self.retry_config.max_delay,
        )

        # Add jitter to prevent synchronized retries
        jitter = delay * self.retry_config.jitter_factor
        return delay + random.uniform(-jitter, jitter)

    async def _dial_addr_single_attempt(self, addr: Multiaddr, peer_id: ID) -> INetConn:
        """
        Enhanced: Single attempt to dial an address (extracted from original dial_addr).

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

    async def dial_addr(self, addr: Multiaddr, peer_id: ID) -> INetConn:
        """
        Enhanced: Try to create a connection to peer_id with addr using retry logic.

        :param addr: the address we want to connect with
        :param peer_id: the peer we want to connect to
        :raises SwarmException: raised when an error occurs
        :return: network connection
        """
        return await self._dial_with_retry(addr, peer_id)

    async def new_stream(self, peer_id: ID) -> INetStream:
        """
        Enhanced: Create a new stream with load balancing across multiple connections.

        :param peer_id: peer_id of destination
        :raises SwarmException: raised when an error occurs
        :return: net stream instance
        """
        logger.debug("attempting to open a stream to peer %s", peer_id)

        # Enhanced: Try to get existing connection from pool first
        if self.connection_pool and self.connection_pool.has_connection(peer_id):
            connection = self.connection_pool.get_connection(
                peer_id, self.connection_config.load_balancing_strategy
            )
            if connection:
                try:
                    net_stream = await connection.new_stream()
                    logger.debug(
                        "successfully opened a stream to peer %s "
                        "using existing connection",
                        peer_id,
                    )
                    return net_stream
                except Exception as e:
                    logger.debug(
                        f"Failed to create stream on existing connection, "
                        f"will dial new connection: {e}"
                    )
                    # Fall through to dial new connection

        # Fall back to existing logic: dial peer and create stream
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
                    conn = self.connections[conn_id]
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
        connection = self.connections[peer_id]

        # Enhanced: Remove from connection pool if enabled
        if self.connection_pool:
            self.connection_pool.remove_connection(peer_id, connection)

        # NOTE: `connection.close` will delete `peer_id` from `self.connections`
        # and `notify_disconnected` for us.
        await connection.close()

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
        # Enhanced: Add to connection pool if enabled
        if self.connection_pool:
            # For incoming connections, we don't have a specific address
            # Use a placeholder that will be updated when we get more info
            self.connection_pool.add_connection(
                muxed_conn.peer_id, swarm_conn, "incoming"
            )

        # Store muxed_conn with peer id (backward compatibility)
        self.connections[muxed_conn.peer_id] = swarm_conn
        # Call notifiers since event occurred
        await self.notify_connected(swarm_conn)
        return swarm_conn

    def remove_conn(self, swarm_conn: SwarmConn) -> None:
        """
        Simply remove the connection from Swarm's records, without closing
        the connection.
        """
        peer_id = swarm_conn.muxed_conn.peer_id

        # Enhanced: Remove from connection pool if enabled
        if self.connection_pool:
            self.connection_pool.remove_connection(peer_id, swarm_conn)

        if peer_id not in self.connections:
            return
        del self.connections[peer_id]

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
