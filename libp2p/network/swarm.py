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
    """
    Configuration for retry logic with exponential backoff.

    This configuration controls how connection attempts are retried when they fail.
    The retry mechanism uses exponential backoff with jitter to prevent thundering
    herd problems in distributed systems.

    Attributes:
        max_retries: Maximum number of retry attempts before giving up.
                     Default: 3 attempts
        initial_delay: Initial delay in seconds before the first retry.
                      Default: 0.1 seconds (100ms)
        max_delay: Maximum delay cap in seconds to prevent excessive wait times.
                  Default: 30.0 seconds
        backoff_multiplier: Multiplier for exponential backoff (each retry multiplies
                           the delay by this factor). Default: 2.0 (doubles each time)
        jitter_factor: Random jitter factor (0.0-1.0) to add randomness to delays
                      and prevent synchronized retries. Default: 0.1 (10% jitter)

    """

    max_retries: int = 3
    initial_delay: float = 0.1
    max_delay: float = 30.0
    backoff_multiplier: float = 2.0
    jitter_factor: float = 0.1


@dataclass
class ConnectionConfig:
    """
    Configuration for multi-connection support.

    This configuration controls how multiple connections per peer are managed,
    including connection limits, timeouts, and load balancing strategies.

    Attributes:
        max_connections_per_peer: Maximum number of connections allowed to a single
                                 peer. Default: 3 connections
        connection_timeout: Timeout in seconds for establishing new connections.
                           Default: 30.0 seconds
        load_balancing_strategy: Strategy for distributing streams across connections.
                                Options: "round_robin" (default) or "least_loaded"

    """

    max_connections_per_peer: int = 3
    connection_timeout: float = 30.0
    load_balancing_strategy: str = "round_robin"  # or "least_loaded"


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
    connections: dict[ID, list[INetConn]]  # Multiple connections per peer
    listeners: dict[str, IListener]
    common_stream_handler: StreamHandlerFn
    listener_nursery: trio.Nursery | None
    event_listener_nursery_created: trio.Event

    notifees: list[INotifee]

    # Enhanced: New configuration
    retry_config: RetryConfig
    connection_config: ConnectionConfig
    _round_robin_index: dict[ID, int]

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

        # Enhanced: Initialize connections as 1:many mapping
        self.connections = {}
        self.listeners = dict()

        # Create Notifee array
        self.notifees = []

        self.common_stream_handler = create_default_stream_handler(self)

        self.listener_nursery = None
        self.event_listener_nursery_created = trio.Event()

        # Load balancing state
        self._round_robin_index = {}

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

    def get_connections(self, peer_id: ID | None = None) -> list[INetConn]:
        """
        Get connections for peer (like JS getConnections, Go ConnsToPeer).

        Parameters
        ----------
        peer_id : ID | None
            The peer ID to get connections for. If None, returns all connections.

        Returns
        -------
        list[INetConn]
            List of connections to the specified peer, or all connections
            if peer_id is None.

        """
        if peer_id is not None:
            return self.connections.get(peer_id, [])

        # Return all connections from all peers
        all_conns = []
        for conns in self.connections.values():
            all_conns.extend(conns)
        return all_conns

    def get_connections_map(self) -> dict[ID, list[INetConn]]:
        """
        Get all connections map (like JS getConnectionsMap).

        Returns
        -------
        dict[ID, list[INetConn]]
            The complete mapping of peer IDs to their connection lists.

        """
        return self.connections.copy()

    def get_connection(self, peer_id: ID) -> INetConn | None:
        """
        Get single connection for backward compatibility.

        Parameters
        ----------
        peer_id : ID
            The peer ID to get a connection for.

        Returns
        -------
        INetConn | None
            The first available connection, or None if no connections exist.

        """
        conns = self.get_connections(peer_id)
        return conns[0] if conns else None

    async def dial_peer(self, peer_id: ID) -> list[INetConn]:
        """
        Try to create connections to peer_id with enhanced retry logic.

        :param peer_id: peer if we want to dial
        :raises SwarmException: raised when an error occurs
        :return: list of muxed connections
        """
        # Check if we already have connections
        existing_connections = self.get_connections(peer_id)
        if existing_connections:
            logger.debug(f"Reusing existing connections to peer {peer_id}")
            return existing_connections

        logger.debug("attempting to dial peer %s", peer_id)

        try:
            # Get peer info from peer store
            addrs = self.peerstore.addrs(peer_id)
        except PeerStoreError as error:
            raise SwarmException(f"No known addresses to peer {peer_id}") from error

        if not addrs:
            raise SwarmException(f"No known addresses to peer {peer_id}")

        connections = []
        exceptions: list[SwarmException] = []

        # Enhanced: Try all known addresses with retry logic
        for multiaddr in addrs:
            try:
                connection = await self._dial_with_retry(multiaddr, peer_id)
                connections.append(connection)

                # Limit number of connections per peer
                if len(connections) >= self.connection_config.max_connections_per_peer:
                    break

            except SwarmException as e:
                exceptions.append(e)
                logger.debug(
                    "encountered swarm exception when trying to connect to %s, "
                    "trying next address...",
                    multiaddr,
                    exc_info=e,
                )

        if not connections:
            # Tried all addresses, raising exception.
            raise SwarmException(
                f"unable to connect to {peer_id}, no addresses established a "
                "successful connection (with exceptions)"
            ) from MultiError(exceptions)

        return connections

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

        # Get existing connections or dial new ones
        connections = self.get_connections(peer_id)
        if not connections:
            connections = await self.dial_peer(peer_id)

        # Load balancing strategy at interface level
        connection = self._select_connection(connections, peer_id)

        try:
            net_stream = await connection.new_stream()
            logger.debug("successfully opened a stream to peer %s", peer_id)
            return net_stream
        except Exception as e:
            logger.debug(f"Failed to create stream on connection: {e}")
            # Try other connections if available
            for other_conn in connections:
                if other_conn != connection:
                    try:
                        net_stream = await other_conn.new_stream()
                        logger.debug(
                            f"Successfully opened a stream to peer {peer_id} "
                            "using alternative connection"
                        )
                        return net_stream
                    except Exception:
                        continue

            # All connections failed, raise exception
            raise SwarmException(f"Failed to create stream to peer {peer_id}") from e

    def _select_connection(self, connections: list[INetConn], peer_id: ID) -> INetConn:
        """
        Select connection based on load balancing strategy.

        Parameters
        ----------
        connections : list[INetConn]
            List of available connections.
        peer_id : ID
            The peer ID for round-robin tracking.
        strategy : str
            Load balancing strategy ("round_robin", "least_loaded", etc.).

        Returns
        -------
        INetConn
            Selected connection.

        """
        if not connections:
            raise ValueError("No connections available")

        strategy = self.connection_config.load_balancing_strategy

        if strategy == "round_robin":
            # Simple round-robin selection
            if peer_id not in self._round_robin_index:
                self._round_robin_index[peer_id] = 0

            index = self._round_robin_index[peer_id] % len(connections)
            self._round_robin_index[peer_id] += 1
            return connections[index]

        elif strategy == "least_loaded":
            # Find connection with least streams
            return min(connections, key=lambda c: len(c.get_streams()))

        else:
            # Default to first connection
            return connections[0]

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
                for peer_id, conns in list(self.connections.items()):
                    for conn in conns:
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
        """
        Close all connections to the specified peer.

        Parameters
        ----------
        peer_id : ID
            The peer ID to close connections for.

        """
        connections = self.get_connections(peer_id)
        if not connections:
            return

        # Close all connections
        for connection in connections:
            try:
                await connection.close()
            except Exception as e:
                logger.warning(f"Error closing connection to {peer_id}: {e}")

        # Remove from connections dict
        self.connections.pop(peer_id, None)

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

        # Add to connections dict with deduplication
        peer_id = muxed_conn.peer_id
        if peer_id not in self.connections:
            self.connections[peer_id] = []

        # Check for duplicate connections by comparing the underlying muxed connection
        for existing_conn in self.connections[peer_id]:
            if existing_conn.muxed_conn == muxed_conn:
                logger.debug(f"Connection already exists for peer {peer_id}")
                # existing_conn is a SwarmConn since it's stored in the connections list
                return existing_conn  # type: ignore[return-value]

        self.connections[peer_id].append(swarm_conn)

        # Trim if we exceed max connections
        max_conns = self.connection_config.max_connections_per_peer
        if len(self.connections[peer_id]) > max_conns:
            self._trim_connections(peer_id)

        # Call notifiers since event occurred
        await self.notify_connected(swarm_conn)
        return swarm_conn

    def _trim_connections(self, peer_id: ID) -> None:
        """
        Remove oldest connections when limit is exceeded.
        """
        connections = self.connections[peer_id]
        if len(connections) <= self.connection_config.max_connections_per_peer:
            return

        # Sort by creation time and remove oldest
        # For now, just keep the most recent connections
        max_conns = self.connection_config.max_connections_per_peer
        connections_to_remove = connections[:-max_conns]

        for conn in connections_to_remove:
            logger.debug(f"Trimming old connection for peer {peer_id}")
            trio.lowlevel.spawn_system_task(self._close_connection_async, conn)

        # Keep only the most recent connections
        max_conns = self.connection_config.max_connections_per_peer
        self.connections[peer_id] = connections[-max_conns:]

    async def _close_connection_async(self, connection: INetConn) -> None:
        """Close a connection asynchronously."""
        try:
            await connection.close()
        except Exception as e:
            logger.warning(f"Error closing connection: {e}")

    def remove_conn(self, swarm_conn: SwarmConn) -> None:
        """
        Simply remove the connection from Swarm's records, without closing
        the connection.
        """
        peer_id = swarm_conn.muxed_conn.peer_id

        if peer_id in self.connections:
            self.connections[peer_id] = [
                conn for conn in self.connections[peer_id] if conn != swarm_conn
            ]
            if not self.connections[peer_id]:
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

    # Backward compatibility properties
    @property
    def connections_legacy(self) -> dict[ID, INetConn]:
        """
        Legacy 1:1 mapping for backward compatibility.

        Returns
        -------
        dict[ID, INetConn]
            Legacy mapping with only the first connection per peer.

        """
        legacy_conns = {}
        for peer_id, conns in self.connections.items():
            if conns:
                legacy_conns[peer_id] = conns[0]
        return legacy_conns
