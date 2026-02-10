from collections.abc import (
    Awaitable,
    Callable,
)
import logging
import random
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from libp2p.network.connection.swarm_connection import SwarmConn

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
    IRawConnection,
    ITransport,
)
from libp2p.custom_types import (
    StreamHandlerFn,
)
from libp2p.io.abc import (
    ReadWriteCloser,
)
from libp2p.network.config import ConnectionConfig, RetryConfig
from libp2p.peer.id import (
    ID,
)
from libp2p.peer.peerstore import (
    PeerStoreError,
)
from libp2p.rcmgr.manager import ResourceManager
from libp2p.security.pnet.protector import new_protected_conn
from libp2p.tools.async_service import (
    Service,
)
from libp2p.transport.exceptions import (
    MuxerUpgradeFailure,
    OpenConnectionError,
    SecurityUpgradeFailure,
)
from libp2p.transport.quic.config import QUICTransportConfig
from libp2p.transport.quic.connection import QUICConnection
from libp2p.transport.quic.transport import QUICTransport
from libp2p.transport.upgrader import (
    TransportUpgrader,
)
from libp2p.utils.multiaddr_utils import (
    extract_ip_from_multiaddr,
)

from ..exceptions import (
    MultiError,
)
from .connection.raw_connection import (
    RawConnection,
)

# SwarmConn is imported conditionally above
from .exceptions import (
    SwarmException,
)

logger = logging.getLogger(__name__)


def create_default_stream_handler(network: INetworkService) -> StreamHandlerFn:
    async def stream_handler(stream: INetStream) -> None:
        await network.get_manager().wait_finished()

    return stream_handler


class Swarm(Service, INetworkService):
    self_id: ID
    peerstore: IPeerStore
    upgrader: TransportUpgrader
    transport: ITransport
    connections: dict[ID, list[INetConn]]
    listeners: dict[str, IListener]
    common_stream_handler: StreamHandlerFn
    listener_nursery: trio.Nursery | None
    event_listener_nursery_created: trio.Event

    notifees: list[INotifee]

    # Enhanced: New configuration
    retry_config: RetryConfig
    connection_config: ConnectionConfig | QUICTransportConfig
    _round_robin_index: dict[ID, int]
    _resource_manager: ResourceManager | None

    def __init__(
        self,
        peer_id: ID,
        peerstore: IPeerStore,
        upgrader: TransportUpgrader,
        transport: ITransport,
        retry_config: RetryConfig | None = None,
        connection_config: ConnectionConfig | QUICTransportConfig | None = None,
        psk: str | None = None,
    ):
        self.self_id = peer_id
        self.peerstore = peerstore
        self.upgrader = upgrader
        self.transport = transport
        self.psk = psk

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
        self._resource_manager = None

    def set_resource_manager(self, resource_manager: ResourceManager | None) -> None:
        """Attach a ResourceManager to wire connection/stream scopes."""
        self._resource_manager = resource_manager

    async def run(self) -> None:
        async with trio.open_nursery() as nursery:
            # Create a nursery for listener tasks.
            self.listener_nursery = nursery

            # Set background nursery BEFORE setting the event
            # This ensures transports have the nursery when they check
            if isinstance(self.transport, QUICTransport):
                self.transport.set_background_nursery(nursery)
                self.transport.set_swarm(self)
            elif hasattr(self.transport, "set_background_nursery"):
                # WebSocket transport also needs background nursery
                # for connection management
                self.transport.set_background_nursery(nursery)  # type: ignore[attr-defined]

            # Now set the event after nursery is set on transport
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
        # Optional pre-upgrade admission on outbound using endpoint from multiaddr
        pre_scope = None
        if self._resource_manager is not None:
            try:
                ep = extract_ip_from_multiaddr(addr)
                pre_scope = self._resource_manager.open_connection(None, endpoint_ip=ep)
                if pre_scope is None:
                    raise SwarmException("Connection denied by resource manager")
            except Exception as e:
                # Fail-open if rate/cidr checks error; keep pre_scope None
                if isinstance(e, SwarmException):
                    raise
                pre_scope = None

        # Dial peer (connection to peer does not yet exist)
        # Transport dials peer (gets back a raw conn)
        try:
            addr = Multiaddr(f"{addr}/p2p/{peer_id}")
            raw_conn = await self.transport.dial(addr)

            # Enable PNET if psk is provvided
            if self.psk is not None:
                raw_conn = new_protected_conn(raw_conn, self.psk)
        except OpenConnectionError as error:
            logger.debug("fail to dial peer %s over base transport", peer_id)
            # Release pre-upgrade scope on failure
            try:
                if pre_scope is not None and hasattr(pre_scope, "close"):
                    pre_scope.close()  # type: ignore[call-arg]
            except Exception:
                pass
            raise SwarmException(
                f"fail to open connection to peer {peer_id}"
            ) from error

        if isinstance(self.transport, QUICTransport) and isinstance(
            raw_conn, IMuxedConn
        ):
            logger.info(
                "Skipping upgrade for QUIC, QUIC connections are already multiplexed"
            )
            swarm_conn = await self.add_conn(raw_conn)
            return swarm_conn

        logger.debug("dialed peer %s over base transport", peer_id)
        swarm_conn = await self.upgrade_outbound_raw_conn(raw_conn, peer_id, pre_scope)

        logger.debug("successfully dialed peer %s", peer_id)

        return swarm_conn

    async def upgrade_outbound_raw_conn(
        self, raw_conn: IRawConnection, peer_id: ID, pre_scope: Any = None
    ) -> "SwarmConn":
        """
        Secure the outgoing raw connection and upgrade it to a multiplexed connection.

        :param raw_conn: the raw connection to upgrade
        :param peer_id: the peer this connection is to
        :raises SwarmException: raised when security or muxer upgrade fails
        :return: network connection with security and multiplexing established
        """
        # Per, https://discuss.libp2p.io/t/multistream-security/130, we first secure
        # the conn and then mux the conn
        try:
            secured_conn = await self.upgrader.upgrade_security(raw_conn, True, peer_id)
        except SecurityUpgradeFailure as error:
            logger.error("failed to upgrade security for peer %s: %s", peer_id, error)
            await raw_conn.close()
            raise SwarmException(
                f"failed to upgrade security for peer {peer_id}: {error}"
            ) from error
        logger.debug("Swarm: security upgrade completed for peer %s", peer_id)

        logger.debug("upgraded security for peer %s", peer_id)

        try:
            muxed_conn = await self.upgrader.upgrade_connection(secured_conn, peer_id)
        except MuxerUpgradeFailure as error:
            logger.debug("failed to upgrade mux for peer %s", peer_id)
            await secured_conn.close()
            raise SwarmException(f"failed to upgrade mux for peer {peer_id}") from error

        logger.debug("Swarm: muxer upgrade completed for peer %s", peer_id)
        logger.debug("upgraded mux for peer %s", peer_id)

        # Pass endpoint IP to resource manager for outbound
        if self._resource_manager is not None:
            try:
                ep = None
                if hasattr(secured_conn, "get_remote_address"):
                    _endpoint = secured_conn.get_remote_address()
                    if _endpoint is not None:
                        ep = _endpoint[0]
                conn_scope = self._resource_manager.open_connection(
                    peer_id, endpoint_ip=ep
                )
                if conn_scope is None:
                    await secured_conn.close()
                    # Release pre-upgrade scope
                    try:
                        if pre_scope is not None and hasattr(pre_scope, "close"):
                            pre_scope.close()  # type: ignore[call-arg]
                            pre_scope = None
                    except Exception:
                        pass
                    raise SwarmException("Connection denied by resource manager")
                try:
                    setattr(muxed_conn, "_resource_scope", conn_scope)
                except Exception:
                    pass
                # Release pre-upgrade scope after acquiring real scope
                try:
                    if pre_scope is not None and hasattr(pre_scope, "close"):
                        pre_scope.close()  # type: ignore[call-arg]
                        pre_scope = None
                except Exception:
                    pass
            except Exception:
                pass

        swarm_conn = await self.add_conn(muxed_conn)
        logger.debug("Swarm: successfully dialed peer %s", peer_id)
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

        # Check resource manager for stream limits
        if self._resource_manager is not None:
            from libp2p.rcmgr import Direction

            if not self._resource_manager.acquire_stream(
                str(peer_id), Direction.OUTBOUND
            ):
                logger.warning("Stream limit exceeded for peer %s", peer_id)
                raise SwarmException("Stream limit exceeded")

        # Get existing connections or dial new ones
        connections = self.get_connections(peer_id)
        if not connections:
            connections = await self.dial_peer(peer_id)

        # Load balancing strategy at interface level
        connection = self._select_connection(connections, peer_id)

        if isinstance(self.transport, QUICTransport) and connection is not None:
            conn = cast("SwarmConn", connection)
            try:
                stream = await conn.new_stream()
                logger.debug("successfully opened a stream to peer %s", peer_id)
                return stream
            except Exception:
                # Release stream resource on failure
                if self._resource_manager is not None:
                    self._resource_manager.release_stream(
                        str(peer_id), Direction.OUTBOUND
                    )
                raise

        try:
            net_stream = await connection.new_stream()
            logger.debug("successfully opened a stream to peer %s", peer_id)
            return net_stream
        except Exception as e:
            logger.debug(f"Failed to create stream on connection: {e}")
            # Release stream resource on failure
            if self._resource_manager is not None:
                self._resource_manager.release_stream(str(peer_id), Direction.OUTBOUND)

            # Try other connections if available
            for other_conn in connections:
                if other_conn != connection:
                    try:
                        # Re-acquire stream resource for alternative connection
                        if self._resource_manager is not None:
                            if not self._resource_manager.acquire_stream(
                                str(peer_id), Direction.OUTBOUND
                            ):
                                continue

                        net_stream = await other_conn.new_stream()
                        logger.debug(
                            f"Successfully opened a stream to peer {peer_id} "
                            "using alternative connection"
                        )
                        return net_stream
                    except Exception:
                        # Release stream resource on failure
                        if self._resource_manager is not None:
                            self._resource_manager.release_stream(
                                str(peer_id), Direction.OUTBOUND
                            )
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
        logger.debug(f"Swarm.listen called with multiaddrs: {multiaddrs}")
        # We need to wait until `self.listener_nursery` is created.
        logger.debug("Starting to listen")
        await self.event_listener_nursery_created.wait()

        success_count = 0
        for maddr in multiaddrs:
            logger.debug(f"Swarm.listen processing multiaddr: {maddr}")
            if str(maddr) in self.listeners:
                logger.debug(f"Swarm.listen: listener already exists for {maddr}")
                success_count += 1
                continue

            async def conn_handler(
                read_write_closer: ReadWriteCloser, maddr: Multiaddr = maddr
            ) -> None:
                # No need to upgrade QUIC Connection
                if isinstance(self.transport, QUICTransport):
                    try:
                        quic_conn = cast(QUICConnection, read_write_closer)
                        await self.add_conn(quic_conn)
                        peer_id = quic_conn.peer_id
                        logger.debug(
                            f"successfully opened quic connection to peer {peer_id}"
                        )
                        # NOTE: This is a intentional barrier to prevent from the
                        # handler exiting and closing the connection.
                        await self.manager.wait_finished()
                    except Exception:
                        await read_write_closer.close()
                    return

                raw_conn = RawConnection(read_write_closer, False)
                try:
                    await self.upgrade_inbound_raw_conn(raw_conn, maddr)
                    # NOTE: This is an intentional barrier to prevent the handler from
                    # exiting and closing the connection.
                    await self.manager.wait_finished()
                except SwarmException as error:
                    # Log the error but don't propagate - this prevents listener crash
                    logger.debug(
                        "connection handler failed to upgrade connection from %s: %s",
                        maddr,
                        error,
                    )
                    await read_write_closer.close()
                except Exception:
                    # Catch any other unexpected errors to prevent listener crash
                    logger.exception(
                        "unexpected error in connection handler for %s",
                        maddr,
                    )
                    await read_write_closer.close()

            try:
                # Success
                logger.debug(f"Swarm.listen: creating listener for {maddr}")
                listener = self.transport.create_listener(conn_handler)
                logger.debug(f"Swarm.listen: listener created for {maddr}")
                self.listeners[str(maddr)] = listener
                # TODO: `listener.listen` is not bounded with nursery. If we want to be
                #   I/O agnostic, we should change the API.
                if self.listener_nursery is None:
                    raise SwarmException("swarm instance hasn't been run")
                assert self.listener_nursery is not None  # For type checker
                logger.debug(f"Swarm.listen: calling listener.listen for {maddr}")
                await listener.listen(maddr, self.listener_nursery)
                logger.debug(f"Swarm.listen: listener.listen completed for {maddr}")

                # Call notifiers since event occurred
                await self.notify_listen(maddr)

                success_count += 1
                logger.debug("successfully started listening on: %s", maddr)
            except OSError:
                # Failed. Continue looping.
                logger.debug("fail to listen on: %s", maddr)

        # Return true if at least one address succeeded
        return success_count > 0

    async def upgrade_inbound_raw_conn(
        self, raw_conn: IRawConnection, maddr: Multiaddr
    ) -> IMuxedConn:
        """
        Secure the inbound raw connection and upgrade it to a multiplexed connection.

        :param raw_conn: the inbound raw connection to upgrade
        :raises SwarmException: raised when security or muxer upgrade fails
        :return: network connection with security and multiplexing established
        """
        logger.debug("upgrade_inbound_raw_conn: starting for %s", maddr)
        # Enable PNET is psk is provided
        if self.psk is not None:
            raw_conn = new_protected_conn(raw_conn, self.psk)

        # secure the conn and then mux the conn
        try:
            logger.debug("upgrade_inbound_raw_conn: upgrading security for %s", maddr)
            secured_conn = await self.upgrader.upgrade_security(raw_conn, False)
            logger.debug("upgrade_inbound: security done for %s", maddr)
        except SecurityUpgradeFailure as error:
            logger.error("failed to upgrade security for peer at %s: %s", maddr, error)
            await raw_conn.close()
            raise SwarmException(
                f"failed to upgrade security for peer at {maddr}"
            ) from error
        peer_id = secured_conn.get_remote_peer()
        logger.debug(
            "upgrade_inbound: peer=%s initiator=%s", peer_id, secured_conn.is_initiator
        )

        try:
            logger.debug("upgrade_inbound: muxer upgrade for %s", peer_id)
            muxed_conn = await self.upgrader.upgrade_connection(secured_conn, peer_id)
            logger.debug("upgrade_inbound: muxer done for %s", peer_id)
        except MuxerUpgradeFailure as error:
            logger.error("fail to upgrade mux for peer %s: %s", peer_id, error)
            await secured_conn.close()
            raise SwarmException(f"fail to upgrade mux for peer {peer_id}") from error
        logger.debug("upgraded mux for peer %s", peer_id)
        # Optional pre-upgrade admission using ResourceManager
        pre_scope = None
        if self._resource_manager is not None:
            try:
                endpoint_ip = None
                if hasattr(raw_conn, "get_remote_address"):
                    ra = raw_conn.get_remote_address()
                    if ra is not None:
                        endpoint_ip = ra[0]
                # Perform a preliminary connection admission to guard early
                pre_scope = self._resource_manager.open_connection(
                    None, endpoint_ip=endpoint_ip
                )
                if pre_scope is None:
                    # Denied before upgrade; close socket and return early
                    await raw_conn.close()
                    return None  # type: ignore[return-value]
            except Exception:
                # Fail-open on admission errors; guard later in add_conn
                pre_scope = None
        # Pass endpoint IP to resource manager, if available
        if self._resource_manager is not None:
            try:
                ep = None
                if hasattr(secured_conn, "get_remote_address"):
                    _endpoint = secured_conn.get_remote_address()
                    if _endpoint is not None:
                        ep = _endpoint[0]
                # open_connection will enforce cidr/rate if configured
                conn_scope = self._resource_manager.open_connection(
                    peer_id, endpoint_ip=ep
                )
                if conn_scope is None:
                    await secured_conn.close()
                    raise SwarmException("Connection denied by resource manager")
                # Store on muxed_conn if possible for cleanup propagation
                try:
                    setattr(muxed_conn, "_resource_scope", conn_scope)
                except Exception:
                    pass
                # Release any pre-upgrade scope now that we have a real scope
                try:
                    if pre_scope is not None and hasattr(pre_scope, "close"):
                        pre_scope.close()  # type: ignore[call-arg]
                        pre_scope = None
                except Exception:
                    pass
            except Exception:
                # Let add_conn perform final guard if needed
                pass

        try:
            await self.add_conn(muxed_conn)
            logger.debug("successfully opened connection to peer %s", peer_id)
        except Exception:
            logger.exception("failed to add connection for peer %s", peer_id)
            await muxed_conn.close()
            return None  # type: ignore[return-value]

        return muxed_conn

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

        # Release stream resources for this peer
        if self._resource_manager is not None:
            # Release all streams for this peer (both inbound and outbound)
            # Note: This is a simplified approach - in a real implementation,
            # we would track individual streams and release them specifically
            logger.debug("Releasing stream resources for peer %s", peer_id)

        # Remove from connections dict
        self.connections.pop(peer_id, None)

        logger.debug("successfully close the connection to peer %s", peer_id)

    async def add_conn(self, muxed_conn: IMuxedConn) -> "SwarmConn":
        """
        Add a `IMuxedConn` to `Swarm` as a `SwarmConn`, notify "connected",
        and start to monitor the connection for its new streams and
        disconnection.
        """
        # Apply resource manager checks to ALL connection types (TCP, WebSocket, QUIC)
        conn_scope = None
        if self._resource_manager is not None:
            try:
                # Extract peer_id from any muxed connection type
                peer_id_for_scope = muxed_conn.peer_id
                conn_scope = self._resource_manager.open_connection(
                    peer_id=peer_id_for_scope,
                )
                if conn_scope is None:
                    # Resource manager denied the connection.
                    # Keep the message concise so it fits within the
                    # project's line-length limit.
                    raise SwarmException(
                        "Connection denied by resource manager: resource limit exceeded"
                    )
                # QUICConnection provides a hook to set scope and ensure cleanup
                if hasattr(muxed_conn, "set_resource_scope"):
                    # Type ignore: we've checked the attribute exists
                    muxed_conn.set_resource_scope(conn_scope)  # type: ignore
            except Exception as e:
                # If resource guard denies, close connection and rethrow
                try:
                    await muxed_conn.close()
                except Exception:
                    pass
                raise SwarmException(f"Connection denied by resource manager: {e}")

        from .connection.swarm_connection import SwarmConn

        swarm_conn = SwarmConn(
            muxed_conn,
            self,
        )

        # For non-QUIC connections, set the resource scope on SwarmConn
        if conn_scope is not None and not hasattr(muxed_conn, "set_resource_scope"):
            swarm_conn.set_resource_scope(conn_scope)  # type: ignore
        logger.debug("Swarm::add_conn | starting muxed connection")
        muxed_type = type(muxed_conn)
        muxed_peer_id = muxed_conn.peer_id
        logger.debug(
            f"Swarm::add_conn | muxed_conn type: {muxed_type}, peer_id: {muxed_peer_id}"
        )
        self.manager.run_task(muxed_conn.start)
        logger.debug(
            f"Swarm::add_conn | waiting for event_started for peer {muxed_conn.peer_id}"
        )
        await muxed_conn.event_started.wait()
        logger.debug(
            f"Swarm::add_conn | event_started received for peer {muxed_conn.peer_id}"
        )
        # For QUIC connections, also verify connection is established
        if isinstance(muxed_conn, QUICConnection):
            if not muxed_conn.is_established:
                await muxed_conn._connected_event.wait()
        logger.debug("Swarm::add_conn | starting swarm connection")
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

    def remove_conn(self, swarm_conn: "SwarmConn") -> None:
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
