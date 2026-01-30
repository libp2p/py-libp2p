from __future__ import annotations

from collections.abc import (
    AsyncIterator,
    Sequence,
)
from contextlib import (
    AbstractAsyncContextManager,
    asynccontextmanager,
)
import logging
from typing import (
    TYPE_CHECKING,
    Any,
)
import weakref

from cryptography import x509
from cryptography.x509.oid import ExtensionOID
import multiaddr
import trio

import libp2p
from libp2p.abc import (
    IHost,
    IMuxedConn,
    INetConn,
    INetStream,
    INetwork,
    INetworkService,
    INotifee,
    IPeerStore,
    IRawConnection,
)
from libp2p.crypto.keys import (
    PrivateKey,
    PublicKey,
)
from libp2p.custom_types import (
    StreamHandlerFn,
    TProtocol,
)
from libp2p.discovery.bootstrap.bootstrap import BootstrapDiscovery
from libp2p.discovery.mdns.mdns import MDNSDiscovery
from libp2p.discovery.upnp.upnp import UpnpManager
from libp2p.host.defaults import (
    get_default_protocols,
)
from libp2p.host.exceptions import (
    StreamFailure,
)
from libp2p.host.ping import (
    ID as PING_PROTOCOL_ID,
)
from libp2p.identity.identify.identify import (
    ID as IdentifyID,
)
from libp2p.identity.identify.pb.identify_pb2 import (
    Identify as IdentifyMsg,
)
from libp2p.identity.identify_push.identify_push import (
    ID_PUSH as IdentifyPushID,
    _update_peerstore_from_identify,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.peer.peerinfo import (
    PeerInfo,
)
from libp2p.peer.peerstore import create_signed_peer_record
from libp2p.protocol_muxer.exceptions import (
    MultiselectClientError,
    MultiselectError,
)
from libp2p.protocol_muxer.multiselect import (
    Multiselect,
)
from libp2p.protocol_muxer.multiselect_client import (
    MultiselectClient,
)
from libp2p.protocol_muxer.multiselect_communicator import (
    MultiselectCommunicator,
)
from libp2p.rcmgr import ResourceManager
from libp2p.relay.circuit_v2.nat import is_private_ip
from libp2p.security.tls.autotls.acme import (
    ACMEClient,
    compute_b36_peer_id,
)
from libp2p.security.tls.autotls.broker import BrokerClient
from libp2p.tools.async_service import (
    background_trio_service,
)
from libp2p.transport.quic.connection import QUICConnection
import libp2p.utils.paths
from libp2p.utils.varint import (
    read_length_prefixed_protobuf,
)

if TYPE_CHECKING:
    from collections import (
        OrderedDict,
    )

# Upon host creation, host takes in options,
# including the list of addresses on which to listen.
# Host then parses these options and delegates to its Network instance,
# telling it to listen on the given listen addresses.

logger = logging.getLogger(__name__)
DEFAULT_NEGOTIATE_TIMEOUT = 30  # Increased to 30s for high-concurrency scenarios
# Under load with 5 concurrent negotiations, some may take longer due to contention

_SAFE_CACHED_PROTOCOLS: set[TProtocol] = {
    PING_PROTOCOL_ID,
    IdentifyID,
    IdentifyPushID,
}
_IDENTIFY_PROTOCOLS: set[TProtocol] = {
    IdentifyID,
    IdentifyPushID,
}


class _IdentifyNotifee(INotifee):
    """
    Network notifee that triggers automatic identify when new connections arrive.
    """

    def __init__(self, host: BasicHost):
        self._host_ref = weakref.ref(host)

    async def connected(self, network: INetwork, conn: INetConn) -> None:
        host = self._host_ref()
        if host is None:
            return
        await host._on_notifee_connected(conn)

    async def disconnected(self, network: INetwork, conn: INetConn) -> None:
        host = self._host_ref()
        if host is None:
            return
        host._on_notifee_disconnected(conn)

    async def opened_stream(self, network: INetwork, stream: INetStream) -> None:
        return None

    async def closed_stream(self, network: INetwork, stream: INetStream) -> None:
        return None

    async def listen(self, network: INetwork, multiaddr: multiaddr.Multiaddr) -> None:
        return None

    async def listen_close(
        self, network: INetwork, multiaddr: multiaddr.Multiaddr
    ) -> None:
        return None


class BasicHost(IHost):
    """
    BasicHost is a wrapper of a `INetwork` implementation.

    It performs protocol negotiation on a stream with multistream-select
    right after a stream is initialized.
    """

    _network: INetworkService
    peerstore: IPeerStore

    multiselect: Multiselect
    multiselect_client: MultiselectClient
    mDNS: MDNSDiscovery | None
    upnp: UpnpManager | None
    bootstrap: BootstrapDiscovery | None

    def __init__(
        self,
        network: INetworkService,
        enable_mDNS: bool = False,
        enable_upnp: bool = False,
        enable_autotls: bool = False,
        bootstrap: list[str] | None = None,
        default_protocols: OrderedDict[TProtocol, StreamHandlerFn] | None = None,
        negotiate_timeout: int = DEFAULT_NEGOTIATE_TIMEOUT,
        resource_manager: ResourceManager | None = None,
        psk: str | None = None,
    ) -> None:
        """
        Initialize a BasicHost instance.

        :param network: Network service implementation
        :param enable_mDNS: Enable mDNS discovery
        :param enable_upnp: Enable UPnP port mapping
        :param bootstrap: Bootstrap peer addresses
        :param default_protocols: Default protocol handlers
        :param negotiate_timeout: Protocol negotiation timeout
        :param resource_manager: Optional resource manager instance
        :type resource_manager: :class:`libp2p.rcmgr.ResourceManager` or None
        """
        self._network = network
        self._network.set_stream_handler(self._swarm_stream_handler)
        self.peerstore = self._network.peerstore

        # Coordinate negotiate_timeout with transport config if available
        # For QUIC transports, use the config value to ensure consistency
        if negotiate_timeout == DEFAULT_NEGOTIATE_TIMEOUT:
            # Try to detect timeout from QUIC transport config
            detected_timeout = self._detect_negotiate_timeout_from_transport()
            if detected_timeout is not None:
                negotiate_timeout = int(detected_timeout)

        self.negotiate_timeout = negotiate_timeout

        # Set up resource manager if provided
        if resource_manager is not None:
            if hasattr(self._network, "set_resource_manager"):
                self._network.set_resource_manager(resource_manager)  # type: ignore
            else:
                # Log warning if network doesn't support resource manager
                logger.warning(
                    "Resource manager provided but network service doesn't support it"
                )
        # Protocol muxing
        default_protocols = default_protocols or get_default_protocols(self)
        self.multiselect = Multiselect(dict(default_protocols.items()))
        self.multiselect_client = MultiselectClient()
        self.mDNS = None
        if enable_mDNS:
            self.mDNS = MDNSDiscovery(network)

        # Initialize bootstrap discovery container. Keep attribute defined so
        # we can avoid hasattr checks elsewhere.
        self.bootstrap = None
        if bootstrap:
            self.bootstrap = BootstrapDiscovery(network, bootstrap)
        self.psk = psk

        # Cache a signed-record if the local-node in the PeerStore
        envelope = create_signed_peer_record(
            self.get_id(),
            self.get_addrs(),
            self.get_private_key(),
        )
        self.get_peerstore().set_local_record(envelope)

        # Initialize UPnP manager if enabled
        # Note: UPnP integration follows the same pattern as mDNS for consistency.
        # The UpnpManager is a standalone component that can be used independently
        # or integrated into the host lifecycle for automatic port management.
        self.upnp = None
        if enable_upnp:
            self.upnp = UpnpManager()

        # Automatic identify coordination
        self._identify_inflight: set[ID] = set()
        self._identified_peers: set[ID] = set()
        self._network.register_notifee(_IdentifyNotifee(self))

    def get_id(self) -> ID:
        """
        :return: peer_id of host
        """
        return self._network.get_peer_id()

    def get_public_key(self) -> PublicKey:
        return self.peerstore.pubkey(self.get_id())

    def get_private_key(self) -> PrivateKey:
        return self.peerstore.privkey(self.get_id())

    def get_network(self) -> INetworkService:
        """
        :return: network instance of host
        """
        return self._network

    def get_peerstore(self) -> IPeerStore:
        """
        :return: peerstore of the host (same one as in its network instance)
        """
        return self.peerstore

    def _detect_negotiate_timeout_from_transport(self) -> float | None:
        """
        Detect negotiate timeout from transport configuration.

        Checks if the network uses a QUIC transport and returns its
        NEGOTIATE_TIMEOUT config value for coordination.

        :return: Negotiate timeout from transport config, or None if not available
        """
        try:
            # Check if network has a transport attribute (Swarm pattern)
            # Type ignore: transport exists on Swarm but not in INetworkService
            if hasattr(self._network, "transport"):
                transport = getattr(self._network, "transport", None)  # type: ignore
                # Check if it's a QUIC transport
                if (
                    transport is not None
                    and hasattr(transport, "_config")
                    and hasattr(transport._config, "NEGOTIATE_TIMEOUT")
                ):
                    timeout = getattr(transport._config, "NEGOTIATE_TIMEOUT", None)  # type: ignore
                    if timeout is not None:
                        logger.debug(
                            f"Detected negotiate timeout {timeout}s "
                            "from QUIC transport config"
                        )
                        return float(timeout)
        except Exception as e:
            # Silently fail - this is optional coordination
            logger.debug(f"Could not detect negotiate timeout from transport: {e}")

        return None

    def get_mux(self) -> Multiselect:
        """
        :return: mux instance of host
        """
        return self.multiselect

    def get_transport_addrs(self) -> list[multiaddr.Multiaddr]:
        """
        Return the raw multiaddr addresses this host is listening to,
        without the /p2p/{peer_id} suffix.
        """
        addrs: list[multiaddr.Multiaddr] = []
        for transport in self._network.listeners.values():
            addrs.extend(transport.get_addrs())
        return addrs

    def get_addrs(self) -> list[multiaddr.Multiaddr]:
        """
        Return all the multiaddr addresses this host is listening to.

        Note: This method appends the /p2p/{peer_id} suffix to the addresses.
        Use get_transport_addrs() for raw transport addresses.
        """
        p2p_part = multiaddr.Multiaddr(f"/p2p/{self.get_id()!s}")
        return [addr.encapsulate(p2p_part) for addr in self.get_transport_addrs()]

    def get_connected_peers(self) -> list[ID]:
        """
        :return: all the ids of peers this host is currently connected to
        """
        return list(self._network.connections.keys())

    def run(
        self,
        listen_addrs: Sequence[multiaddr.Multiaddr],
        *,
        task_status: Any = trio.TASK_STATUS_IGNORED,
    ) -> AbstractAsyncContextManager[None]:
        """
        Run the host instance and listen to ``listen_addrs``.

        :param listen_addrs: a sequence of multiaddrs that we want to listen to
        :param task_status: task status for trio nursery compatibility (ignored)
        """

        @asynccontextmanager
        async def _run() -> AsyncIterator[None]:
            network = self.get_network()
            async with background_trio_service(network):
                await network.listen(*listen_addrs)
                if self.mDNS is not None:
                    logger.debug("Starting mDNS Discovery")
                    self.mDNS.start()
                if self.upnp is not None:
                    upnp_manager = self.upnp
                    logger.debug("Starting UPnP discovery and port mapping")
                    if await upnp_manager.discover():
                        for addr in self.get_addrs():
                            if port := addr.value_for_protocol("tcp"):
                                await upnp_manager.add_port_mapping(int(port), "TCP")
                if self.bootstrap is not None:
                    logger.debug("Starting Bootstrap Discovery")
                    await self.bootstrap.start()

                try:
                    yield
                finally:
                    if self.mDNS is not None:
                        self.mDNS.stop()
                    if self.upnp and self.upnp.get_external_ip():
                        upnp_manager = self.upnp
                        logger.debug("Removing UPnP port mappings")
                        for addr in self.get_addrs():
                            if port := addr.value_for_protocol("tcp"):
                                await upnp_manager.remove_port_mapping(int(port), "TCP")
                    if self.bootstrap is not None:
                        self.bootstrap.stop()

        return _run()

    def set_stream_handler(
        self, protocol_id: TProtocol, stream_handler: StreamHandlerFn
    ) -> None:
        """
        Set stream handler for given `protocol_id`

        :param protocol_id: protocol id used on stream
        :param stream_handler: a stream handler function
        """
        self.multiselect.add_handler(protocol_id, stream_handler)

    def _preferred_protocol(
        self, peer_id: ID, protocol_ids: Sequence[TProtocol]
    ) -> TProtocol | None:
        """
        Check if the peerstore says the remote peer supports any of the
        requested protocols.

        We still perform the multiselect negotiation, but if we already know the
        matching protocol we can request it directly (instead of trying the full
        list) which reduces time spent inside select_one_of.

        Note: Protocol caching only works for well-known protocols (ping, identify)
        to avoid issues with protocols that require proper negotiation.

        :param peer_id: peer ID to check
        :param protocol_ids: list of protocol IDs to check
        :return: first supported protocol, or None if not cached
        """
        try:
            # Check if peer exists in peerstore first (avoid auto-creation)
            if peer_id not in self.peerstore.peer_ids():
                return None

            # Only use protocol caching if we have a connection to this peer
            # This ensures identify has completed
            connections = self._network.connections.get(peer_id, [])
            if not connections:
                return None

            # Only cache protocols that are in the safe list
            cacheable_ids = [
                p
                for p in protocol_ids
                if p in _SAFE_CACHED_PROTOCOLS and p not in _IDENTIFY_PROTOCOLS
            ]
            if not cacheable_ids:
                return None

            # Query peerstore for supported protocols
            # This returns protocols in the order they appear in protocol_ids
            supported = self.peerstore.supports_protocols(
                peer_id, [str(p) for p in cacheable_ids]
            )
            if supported:
                # Return the first supported protocol (cast back to TProtocol)
                return TProtocol(supported[0])
            # If we reached here, we don't have cached entries yet. Kick off identify
            # in the background so future streams can skip negotiation.
            self._schedule_identify(peer_id, reason="preferred-protocol")
        except Exception as e:
            # If peer not in peerstore or any error, fall back to negotiation
            logger.debug(
                f"Could not query peerstore for peer {peer_id}: {e}. "
                "Will negotiate protocol."
            )
        return None

    async def initiate_autotls_procedure(self, public_ip: str | None = None) -> None:
        """
        Run the AutoTLS certificate provisioning flow for this host.

        If a cached ACME certificate already exists on disk, it is loaded and validated
        and procedure exists early. Otherwise the method performs the full AutoTLS flow:

        - create or load an ACME account bound to the host's identity key
        - initiate a certificate order
        - obtain a DNS-01 challenge
        - discover a publicly reachable IPv4 address from the host's listen addrs
        - register the challenge with the AutoTLS broker
        - wait for DNS propagation
        - finalize the order and fetch the certificate

        Only publicly reachable IPv4 addresses are considered valid for AutoTLS.
        If no such address can be determined, the procedure fails.

        :param public_ip: Optional externally known public IPv4 address. If not
            provided, the address is inferred from the host's transport addresses.
        :return: None
        :raises RuntimeError: if no publicly reachable IPv4 address can be determined
            for DNS challenge registration.
        """
        if libp2p.utils.paths.AUTOTLS_CERT_PATH.exists():
            pem_bytes = libp2p.utils.paths.AUTOTLS_CERT_PATH.read_bytes()
            cert_chain = x509.load_pem_x509_certificates(pem_bytes)

            san = (
                cert_chain[0]
                .extensions.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME)
                .value
            )
            # DNS names
            dns_names = san.get_values_for_type(x509.DNSName)  # type: ignore
            b36_pid = compute_b36_peer_id(self.get_id())

            logger.info(
                "AutoTLS procedure: Loaded existing cert, DNS: %s, b36_pid: %s",
                dns_names,
                b36_pid,
            )

            return

        logger.info("ACME certificate not cached, initiating the procedure...")
        acme = ACMEClient(self.get_private_key(), self.get_id())
        await acme.create_acme_acct()
        await acme.initiate_order()
        await acme.get_dns01_challenge()

        # Extract public IP from host's listening addresses
        # According to spec, only publicly reachable IP addresses
        # should be sent to broker.
        # Use get_transport_addrs() to get addresses without /p2p/{peer_id} suffix

        # For some reason this way of extracting pub-addr is working on Luca's end
        # but not on mine

        all_addrs = self.get_transport_addrs()
        if public_ip is None:
            for addr in all_addrs:
                try:
                    ip = addr.value_for_protocol("ip4")
                    if ip and not is_private_ip(ip):
                        public_ip = ip
                        port = addr.value_for_protocol("tcp")
                        if port:
                            break
                except Exception:
                    continue

            if not public_ip or not port:
                raise RuntimeError(
                    "No public IP address found in listening addresses. "
                    "AutoTLS requires at least one publicly reachable IPv4 address."
                )
        port = self.get_addrs()[0].value_for_protocol("tcp")

        broker = BrokerClient(
            self.get_private_key(),
            multiaddr.Multiaddr(f"/ip4/{public_ip}/tcp/{port}/p2p/{self.get_id()}"),
            acme.key_auth,
            acme.b36_peerid,
        )

        await broker.http_peerid_auth()
        await broker.wait_for_dns()

        await acme.notify_dns_ready()
        await acme.fetch_cert_url()
        await acme.fetch_certificate()

        return

    async def new_stream(
        self,
        peer_id: ID,
        protocol_ids: Sequence[TProtocol],
    ) -> INetStream:
        """
        :param peer_id: peer_id that host is connecting
        :param protocol_ids: available protocol ids to use for stream
        :return: stream: new stream created
        """
        semaphore_to_use: trio.Semaphore | None = None
        semaphore_acquired = False

        # Attempt to grab the negotiation semaphore before opening the stream so
        # we don't create more QUIC streams than we can immediately negotiate.
        existing_connection = self._get_first_connection(peer_id)
        if existing_connection is not None:
            existing_muxed_conn = getattr(existing_connection, "muxed_conn", None)
            if existing_muxed_conn is not None:
                semaphore_to_use = getattr(
                    existing_muxed_conn, "_negotiation_semaphore", None
                )
        if semaphore_to_use is not None:
            acquire_start = trio.current_time()
            await semaphore_to_use.acquire()
            semaphore_acquired = True
            acquire_duration = (trio.current_time() - acquire_start) * 1000
            if acquire_duration > 5 and logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Waited %.2fms to acquire negotiation slot for peer %s "
                    "before opening stream",
                    acquire_duration,
                    peer_id,
                )

        net_stream = await self._network.new_stream(peer_id)

        protocol_choices = list(protocol_ids)
        # Check if we already know the peer supports any of these protocols
        # from the identify exchange. If so, request that protocol directly
        # but still run the multiselect handshake to keep both sides in sync.
        preferred = self._preferred_protocol(peer_id, protocol_ids)
        if preferred is not None:
            logger.debug(
                f"Using cached protocol {preferred} for peer {peer_id}, "
                "requesting it directly"
            )
            protocol_choices = [preferred]

        try:
            muxed_conn = getattr(net_stream, "muxed_conn", None)
            stream_semaphore = (
                getattr(muxed_conn, "_negotiation_semaphore", None)
                if muxed_conn is not None
                else None
            )

            if stream_semaphore is not None:
                if semaphore_to_use is not stream_semaphore:
                    if semaphore_acquired and semaphore_to_use is not None:
                        semaphore_to_use.release()
                    semaphore_to_use = stream_semaphore
                    semaphore_acquired = False

                if not semaphore_acquired and semaphore_to_use is not None:
                    acquire_start = trio.current_time()
                    await semaphore_to_use.acquire()
                    semaphore_acquired = True
                    acquire_duration = (trio.current_time() - acquire_start) * 1000
                    if acquire_duration > 5 and logger.isEnabledFor(logging.DEBUG):
                        logger.debug(
                            "Waited %.2fms to acquire negotiation slot for peer %s "
                            "after stream creation",
                            acquire_duration,
                            peer_id,
                        )

            communicator = MultiselectCommunicator(net_stream)
            selected_protocol = await self.multiselect_client.select_one_of(
                protocol_choices,
                communicator,
                self.negotiate_timeout,
            )
        except MultiselectClientError as error:
            # Enhanced error logging for debugging
            error_msg = str(error)
            connection_type = "unknown"
            is_established = False
            handshake_completed = False
            registry_stats = None

            # Get connection state if available
            muxed_conn = getattr(net_stream, "muxed_conn", None)
            if muxed_conn is not None:
                connection_type = type(muxed_conn).__name__
                if hasattr(muxed_conn, "is_established"):
                    is_established = (
                        muxed_conn.is_established
                        if not callable(muxed_conn.is_established)
                        else muxed_conn.is_established()
                    )
                if hasattr(muxed_conn, "_handshake_completed"):
                    handshake_completed = muxed_conn._handshake_completed

                # Get registry stats if QUIC connection
                # Try to get stats from server listener (for server-side connections)
                # or from client transport's listeners (if available)
                if connection_type == "QUICConnection" and hasattr(
                    muxed_conn, "_transport"
                ):
                    transport = getattr(muxed_conn, "_transport", None)
                    if transport:
                        # Try to get listener from transport
                        listeners = getattr(transport, "_listeners", [])
                        if listeners and len(listeners) > 0:
                            listener = listeners[0]
                            if listener and hasattr(listener, "_registry"):
                                registry = getattr(listener, "_registry", None)
                                if registry:
                                    try:
                                        registry_stats = registry.get_lock_stats()
                                    except Exception:
                                        registry_stats = None
                        # Also try to get stats from connection's listener
                        # if it's an inbound connection
                        if registry_stats is None and hasattr(muxed_conn, "_listener"):
                            listener = getattr(muxed_conn, "_listener", None)
                            if listener and hasattr(listener, "_registry"):
                                registry = getattr(listener, "_registry", None)
                                if registry:
                                    try:
                                        registry_stats = registry.get_lock_stats()
                                    except Exception:
                                        registry_stats = None

            # Log detailed error information
            logger.error(
                f"Failed to open stream to peer {peer_id}:\n"
                f"  Error: {error_msg}\n"
                f"  Protocols: {list(protocol_ids)}\n"
                f"  Timeout: {self.negotiate_timeout}s\n"
                f"  Connection: {connection_type}\n"
                f"  Connection State: established={is_established}, "
                f"handshake={handshake_completed}\n"
                f"  Registry Stats: {registry_stats}"
            )

            await net_stream.reset()
            raise StreamFailure(f"failed to open a stream to peer {peer_id}") from error
        finally:
            if semaphore_acquired and semaphore_to_use is not None:
                semaphore_to_use.release()

        net_stream.set_protocol(selected_protocol)
        return net_stream

    async def send_command(
        self,
        peer_id: ID,
        command: str,
        response_timeout: int = DEFAULT_NEGOTIATE_TIMEOUT,
    ) -> list[str]:
        """
        Send a multistream-select command to the specified peer and return
        the response.

        :param peer_id: peer_id that host is connecting
        :param command: supported multistream-select command (e.g., "ls)
        :raise StreamFailure: If the stream cannot be opened or negotiation fails
        :return: list of strings representing the response from peer.
        """
        new_stream = await self._network.new_stream(peer_id)

        try:
            response = await self.multiselect_client.query_multistream_command(
                MultiselectCommunicator(new_stream), command, response_timeout
            )
        except MultiselectClientError as error:
            logger.debug("fail to open a stream to peer %s, error=%s", peer_id, error)
            await new_stream.reset()
            raise StreamFailure(f"failed to open a stream to peer {peer_id}") from error

        return response

    async def connect(self, peer_info: PeerInfo) -> None:
        """
        Ensure there is a connection between this host and the peer
        with given `peer_info.peer_id`. connect will absorb the addresses in
        peer_info into its internal peerstore. If there is not an active
        connection, connect will issue a dial, and block until a connection is
        opened, or an error is returned.

        This method ensures the connection is fully established and ready for
        streams before returning, including:
        - QUIC handshake completion
        - Muxer initialization
        - Connection registration in swarm
        - Stream handler readiness

        :param peer_info: peer_info of the peer we want to connect to
        :type peer_info: peer.peerinfo.PeerInfo
        """
        self.peerstore.add_addrs(peer_info.peer_id, peer_info.addrs, 120)

        # there is already a connection to this peer
        if peer_info.peer_id in self._network.connections:
            connections = self._network.connections[peer_info.peer_id]
            if connections:
                # Verify existing connection is ready
                swarm_conn = connections[0]
                if (
                    hasattr(swarm_conn, "event_started")
                    and not swarm_conn.event_started.is_set()
                ):
                    await swarm_conn.event_started.wait()
                return

        # Dial the peer - this will call add_conn which waits for event_started
        connections = await self._network.dial_peer(peer_info.peer_id)

        # Ensure connection is fully ready before returning
        # dial_peer returns INetConn (SwarmConn) objects which have event_started
        if connections:
            swarm_conn = connections[0]
            # Wait for connection to be fully started and ready for streams
            # SwarmConn has event_started which is set after muxer and
            # stream handlers are ready
            if hasattr(swarm_conn, "event_started"):
                await swarm_conn.event_started.wait()

            # Kick off identify in the background so protocol caching can engage.
            self._schedule_identify(peer_info.peer_id, reason="connect")

    async def _run_identify(self, peer_id: ID) -> None:
        """
        Run identify protocol with a peer to discover supported protocols.

        This method opens an identify stream, receives the peer's information,
        and stores the supported protocols in the peerstore for later use.
        This enables protocol caching to skip multiselect negotiation.

        :param peer_id: ID of the peer to identify
        """
        try:
            # Import here to avoid circular dependency
            from libp2p.identity.identify.identify import (
                ID as IDENTIFY_ID,
            )
            from libp2p.identity.identify_push.identify_push import (
                _update_peerstore_from_identify,
                read_length_prefixed_protobuf,
            )

            # Open identify stream (this will use multiselect negotiation)
            stream = await self.new_stream(peer_id, [IDENTIFY_ID])

            # Read identify response (length-prefixed protobuf)
            response = await read_length_prefixed_protobuf(
                stream, use_varint_format=True
            )
            await stream.close()

            # Parse the identify message
            from libp2p.identity.identify.pb.identify_pb2 import Identify

            identify_msg = Identify()
            identify_msg.ParseFromString(response)

            # Store protocols in peerstore
            await _update_peerstore_from_identify(self.peerstore, peer_id, identify_msg)

            logger.debug(
                f"Identify completed for peer {peer_id}, "
                f"protocols: {list(identify_msg.protocols)}"
            )
        except Exception as e:
            # Don't fail the connection if identify fails
            # Protocol caching just won't be available for this peer
            logger.debug(f"Failed to run identify for peer {peer_id}: {e}")

    async def disconnect(self, peer_id: ID) -> None:
        await self._network.close_peer(peer_id)

    async def close(self) -> None:
        await self._network.close()

    def _schedule_identify(self, peer_id: ID, *, reason: str) -> None:
        """
        Ensure identify is running for `peer_id`. If a task is already running or
        cached protocols exist, this is a no-op.
        """
        if (
            peer_id == self.get_id()
            or self._has_cached_protocols(peer_id)
            or peer_id in self._identify_inflight
        ):
            return
        if not self._should_identify_peer(peer_id):
            return
        self._identify_inflight.add(peer_id)
        trio.lowlevel.spawn_system_task(self._identify_task_entry, peer_id, reason)

    async def _identify_task_entry(self, peer_id: ID, reason: str) -> None:
        try:
            await self._identify_peer(peer_id, reason=reason)
        finally:
            self._identify_inflight.discard(peer_id)

    def _has_cached_protocols(self, peer_id: ID) -> bool:
        """
        Return True if the peerstore already lists any safe cached protocol for
        the peer (e.g. ping/identify), meaning identify already succeeded.
        """
        if peer_id in self._identified_peers:
            return True
        cacheable = [str(p) for p in _SAFE_CACHED_PROTOCOLS]
        try:
            if peer_id not in self.peerstore.peer_ids():
                return False
            supported = self.peerstore.supports_protocols(peer_id, cacheable)
            return bool(supported)
        except Exception:
            return False

    async def _identify_peer(self, peer_id: ID, *, reason: str) -> None:
        """
        Open an identify stream to the peer and update the peerstore with the
        advertised protocols and addresses.
        """
        connections = self._network.get_connections(peer_id)
        if not connections:
            return

        swarm_conn = connections[0]
        event_started = getattr(swarm_conn, "event_started", None)
        if event_started is not None and not event_started.is_set():
            try:
                await event_started.wait()
            except Exception:
                return

        try:
            stream = await self.new_stream(peer_id, [IdentifyID])
        except Exception as exc:
            logger.debug("Identify[%s]: failed to open stream: %s", reason, exc)
            return

        try:
            data = await read_length_prefixed_protobuf(stream, use_varint_format=True)
            identify_msg = IdentifyMsg()
            identify_msg.ParseFromString(data)
            await _update_peerstore_from_identify(self.peerstore, peer_id, identify_msg)
            self._identified_peers.add(peer_id)
            logger.debug(
                "Identify[%s]: cached %s protocols for peer %s",
                reason,
                len(identify_msg.protocols),
                peer_id,
            )
        except Exception as exc:
            logger.debug("Identify[%s]: error reading response: %s", reason, exc)
            try:
                await stream.reset()
            except Exception:
                pass
        finally:
            try:
                await stream.close()
            except Exception:
                pass

    async def _on_notifee_connected(self, conn: INetConn) -> None:
        peer_id = getattr(conn.muxed_conn, "peer_id", None)
        if peer_id is None:
            return
        muxed_conn = getattr(conn, "muxed_conn", None)
        is_initiator = False
        if muxed_conn is not None and hasattr(muxed_conn, "is_initiator"):
            try:
                is_initiator = bool(muxed_conn.is_initiator())
            except Exception:
                is_initiator = False
        if not is_initiator:
            # Only the dialer (initiator) needs to actively run identify.
            return
        if not self._is_quic_muxer(muxed_conn):
            return
        event_started = getattr(conn, "event_started", None)
        if event_started is not None and not event_started.is_set():
            try:
                await event_started.wait()
            except Exception:
                return
        self._schedule_identify(peer_id, reason="notifee-connected")

    def _on_notifee_disconnected(self, conn: INetConn) -> None:
        peer_id = getattr(conn.muxed_conn, "peer_id", None)
        if peer_id is None:
            return
        self._identified_peers.discard(peer_id)

    def _get_first_connection(self, peer_id: ID) -> INetConn | None:
        connections = self._network.get_connections(peer_id)
        if connections:
            return connections[0]
        return None

    def _is_quic_muxer(self, muxed_conn: IMuxedConn | None) -> bool:
        return isinstance(muxed_conn, QUICConnection)

    def _should_identify_peer(self, peer_id: ID) -> bool:
        connection = self._get_first_connection(peer_id)
        if connection is None:
            return False
        muxed_conn = getattr(connection, "muxed_conn", None)
        return self._is_quic_muxer(muxed_conn)

    # Reference: `BasicHost.newStreamHandler` in Go.
    async def _swarm_stream_handler(self, net_stream: INetStream) -> None:
        # Perform protocol muxing to determine protocol to use
        # For QUIC connections, use connection-level semaphore to limit
        # concurrent negotiations and prevent server-side overload
        # This matches the client-side protection for symmetric behavior
        muxed_conn = getattr(net_stream, "muxed_conn", None)
        negotiation_semaphore = None
        if muxed_conn is not None:
            negotiation_semaphore = getattr(muxed_conn, "_negotiation_semaphore", None)

        try:
            if negotiation_semaphore is not None:
                # Use connection-level server semaphore to throttle
                # server-side negotiations. This prevents server overload
                # when many streams arrive simultaneously.
                # Use separate server semaphore to avoid deadlocks
                # with client negotiations.
                muxed_conn = getattr(net_stream, "muxed_conn", None)
                server_semaphore = None
                if muxed_conn is not None:
                    server_semaphore = getattr(
                        muxed_conn, "_server_negotiation_semaphore", None
                    )
                # Fallback to shared semaphore if server semaphore not available
                semaphore_to_use = server_semaphore or negotiation_semaphore
                async with semaphore_to_use:
                    protocol, handler = await self.multiselect.negotiate(
                        MultiselectCommunicator(net_stream), self.negotiate_timeout
                    )
            else:
                # For non-QUIC connections, negotiate directly (no semaphore needed)
                protocol, handler = await self.multiselect.negotiate(
                    MultiselectCommunicator(net_stream), self.negotiate_timeout
                )
            if protocol is None:
                await net_stream.reset()
                raise StreamFailure(
                    "Failed to negotiate protocol: no protocol selected"
                )
        except MultiselectError as error:
            peer_id = net_stream.muxed_conn.peer_id
            logger.debug(
                "failed to accept a stream from peer %s, error=%s", peer_id, error
            )
            await net_stream.reset()
            return
        if protocol is None:
            logger.debug(
                "no protocol negotiated, closing stream from peer %s",
                net_stream.muxed_conn.peer_id,
            )
            await net_stream.reset()
            return
        net_stream.set_protocol(protocol)
        if handler is None:
            logger.debug(
                "no handler for protocol %s, closing stream from peer %s",
                protocol,
                net_stream.muxed_conn.peer_id,
            )
            await net_stream.reset()
            return

        await handler(net_stream)

    def get_live_peers(self) -> list[ID]:
        """
        Returns a list of currently connected peer IDs.

        :return: List of peer IDs that have active connections
        """
        return list(self._network.connections.keys())

    def is_peer_connected(self, peer_id: ID) -> bool:
        """
        Check if a specific peer is currently connected.

        :param peer_id: ID of the peer to check
        :return: True if peer has an active connection, False otherwise
        """
        return len(self._network.get_connections(peer_id)) > 0

    def get_peer_connection_info(self, peer_id: ID) -> list[INetConn] | None:
        """
        Get connection information for a specific peer if connected.

        :param peer_id: ID of the peer to get info for
        :return: Connection object if peer is connected, None otherwise
        """
        return self._network.connections.get(peer_id)

    async def upgrade_outbound_connection(
        self, raw_conn: IRawConnection, peer_id: ID
    ) -> INetConn:
        """
        Upgrade a raw outbound connection for the peer_id using the underlying network.

        :param raw_conn: The raw connection to upgrade.
        :param peer_id: The peer this connection is to.
        :raises SwarmException: raised when security or muxer upgrade fails
        :return: network connection with security and multiplexing established
        """
        return await self._network.upgrade_outbound_raw_conn(raw_conn, peer_id)

    async def upgrade_inbound_connection(
        self, raw_conn: IRawConnection, maddr: multiaddr.Multiaddr
    ) -> IMuxedConn:
        """
        Upgrade a raw inbound connection using the underlying network.

        :param raw_conn: The inbound raw connection to upgrade.
        :param maddr: The multiaddress this connection arrived on.
        :raises SwarmException: raised when security or muxer upgrade fails
        :return: network connection with security and multiplexing established
        """
        return await self._network.upgrade_inbound_raw_conn(raw_conn, maddr)
