"""
Transport implementation for Circuit Relay v2.

This module implements the transport layer for Circuit Relay v2,
allowing peers to establish connections through relay nodes.
"""

import logging
import time
from typing import Any, cast

import multiaddr
import trio

from libp2p.abc import (
    IHost,
    IListener,
    INetConn,
    INetStream,
    IRawConnection,
    ITransport,
)
from libp2p.custom_types import (
    THandler,
)
from libp2p.kad_dht.kad_dht import DHTMode, KadDHT
from libp2p.network.connection.raw_connection import (
    RawConnection,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.peer.peerinfo import (
    PeerInfo,
)
from libp2p.peer.peerstore import env_to_send_in_RPC
from libp2p.tools.async_service import (
    Service,
)

from .config import (
    ClientConfig,
    RelayConfig,
)
from .discovery import (
    RelayDiscovery,
)
from .pb.circuit_pb2 import (
    HopMessage,
    StopMessage,
)
from .performance_tracker import (
    RelayPerformanceTracker,
)
from .protocol import (
    PROTOCOL_ID,
    STREAM_READ_TIMEOUT,
    CircuitV2Protocol,
    INetStreamWithExtras,
)
from .protocol_buffer import (
    StatusCode,
)
from .utils import (
    maybe_consume_signed_record,
)

logger = logging.getLogger(__name__)
TOP_N = 3
RESERVATION_REFRESH_INTERVAL = 10  # seconds
RESERVATION_REFRESH_MARGIN = 30  # seconds


class TrackedRawConnection(IRawConnection):
    """
    Wrapper around RawConnection that tracks circuit closure.

    Automatically calls record_circuit_closed() when the connection is closed.
    This ensures that active circuit counts are properly decremented when
    connections are closed, preventing unbounded growth of circuit counts.
    """

    _wrapped: RawConnection
    _relay_id: ID
    _tracker: RelayPerformanceTracker
    _closed: bool = False

    def __init__(
        self,
        wrapped: RawConnection,
        relay_id: ID,
        tracker: RelayPerformanceTracker,
    ) -> None:
        """
        Initialize the tracked connection wrapper.

        Args:
            wrapped: The RawConnection to wrap
            relay_id: The relay peer ID for tracking
            tracker: The performance tracker to notify on closure

        """
        self._wrapped = wrapped
        self._relay_id = relay_id
        self._tracker = tracker

    async def close(self) -> None:
        """Close the connection and record circuit closure."""
        if not self._closed:
            self._closed = True
            await self._wrapped.close()
            self._tracker.record_circuit_closed(self._relay_id)

    async def write(self, data: bytes) -> None:
        """Write data to the wrapped connection."""
        return await self._wrapped.write(data)

    async def read(self, n: int | None = None) -> bytes:
        """Read data from the wrapped connection."""
        return await self._wrapped.read(n)

    def get_remote_address(self) -> tuple[str, int] | None:
        """Get remote address from the wrapped connection."""
        return self._wrapped.get_remote_address()

    def __getattr__(self, name: str) -> Any:
        """Delegate attribute access to wrapped connection."""
        return getattr(self._wrapped, name)


class CircuitV2Transport(ITransport):
    """
    CircuitV2Transport implements the transport interface for Circuit Relay v2.

    This transport allows peers to establish connections through relay nodes
    when direct connections are not possible.
    """

    def __init__(
        self,
        host: IHost,
        protocol: CircuitV2Protocol,
        config: RelayConfig,
    ) -> None:
        """
        Initialize the Circuit v2 transport.

        Parameters
        ----------
        host : IHost
            The libp2p host this transport is running on
        protocol : CircuitV2Protocol
            The Circuit v2 protocol instance
        config : RelayConfig
            Relay configuration

        """
        self.host = host
        self.protocol = protocol
        self.config = config
        self.client_config = ClientConfig()
        self.discovery = RelayDiscovery(
            host=host,
            auto_reserve=config.enable_client,
            discovery_interval=config.discovery_interval,
            max_relays=config.max_relays,
            stream_timeout=config.timeouts.discovery_stream_timeout,
            peer_protocol_timeout=config.timeouts.peer_protocol_timeout,
        )
        # Performance tracking (from HEAD)
        self.relay_counter = 0  # for round robin load balancing
        # A lock to protect ``relay_counter`` from concurrent access since
        # ``_select_relay`` may be invoked from multiple tasks concurrently.
        self._relay_counter_lock = trio.Lock()

        # Performance tracker for intelligent relay selection
        self.performance_tracker = RelayPerformanceTracker()

        # Stored addresses and DHT (from origin/main)
        self._last_relay_index = -1
        self._relay_list: list[ID] = []
        self._relay_metrics: dict[ID, dict[str, float | int]] = {}
        self._reservations: dict[ID, float] = {}
        self._refreshing = False
        self.dht: KadDHT | None = None
        if config.enable_dht_discovery:
            self.dht = KadDHT(host, DHTMode.CLIENT)

    async def dial(  # type: ignore[override]
        self,
        maddr: multiaddr.Multiaddr,
    ) -> INetConn:
        """
        Dial a peer using the multiaddr.

        Parameters
        ----------
        maddr : multiaddr.Multiaddr
            The multiaddr to dial

        Returns
        -------
        INetConn
            The established connection

        Raises
        ------
        ConnectionError
            If the connection cannot be established

        """
        # Extract peer ID from multiaddr - P_P2P code is 0x01A5 (421)
        relay_id_str = None
        relay_maddr = None
        dest_id_str = None
        found_circuit = False
        relay_maddr_end_index = None

        for idx, (proto, value) in enumerate(maddr.items()):
            if proto.name == "p2p-circuit":
                found_circuit = True
                relay_maddr_end_index = idx
            elif proto.name == "p2p":
                if not found_circuit and relay_id_str is None:
                    relay_id_str = value
                elif found_circuit and dest_id_str is None:
                    dest_id_str = value

        if relay_id_str is not None and relay_maddr_end_index is not None:
            relay_maddr = multiaddr.Multiaddr(
                "/".join(str(maddr).split("/")[: relay_maddr_end_index * 2 + 1])
            )
        if not relay_id_str:
            raise ConnectionError("Multiaddr does not contain relay peer ID")
        if not dest_id_str:
            raise ConnectionError(
                "Multiaddr does not contain destination peer ID after p2p-circuit"
            )

        logger.debug(f"Relay peer ID: {relay_id_str} , \n {relay_maddr}")

        dest_info = PeerInfo(ID.from_string(dest_id_str), [maddr])
        logger.debug(f"Dialing destination peer ID: {dest_id_str} , \n {maddr}")
        # Use the internal dial_peer_info method
        if isinstance(relay_id_str, str):
            relay_peer_id = ID.from_string(relay_id_str)
        elif isinstance(relay_id_str, ID):
            relay_peer_id = relay_id_str
        else:
            raise ConnectionError("relay_id_str must be a string or ID")
        relay_addrs = [relay_maddr] if relay_maddr is not None else []
        relay_peer_info = PeerInfo(relay_peer_id, relay_addrs)
        raw_conn = await self.dial_peer_info(
            dest_info=dest_info, relay_info=relay_peer_info
        )
        i_net_conn = await self.host.upgrade_outbound_connection(
            raw_conn, dest_info.peer_id
        )
        return i_net_conn

    async def dial_peer_info(
        self,
        dest_info: PeerInfo,
        *,
        relay_info: PeerInfo | None = None,
    ) -> IRawConnection:
        """
        Dial a destination peer using a relay.

        Parameters
        ----------
        dest_info : PeerInfo
            The destination peer to dial.
        relay_info : Optional[PeerInfo], optional
            An optional specific relay peer to use.

        Returns
        -------
        RawConnection
            The established raw connection to the destination peer through the relay.

        Raises
        ------
        ConnectionError
            If the connection cannot be established.

        """
        # Track connection start time for latency measurement
        connection_start_time = trio.current_time()

        # Prefer stored /p2p-circuit addrs from peerstore
        # Try first to read addresses from peerstore
        peer_store = self.host.get_peerstore()

        stored_addrs = []
        try:
            stored_addrs = peer_store.addrs(dest_info.peer_id)
        except Exception as e:
            logger.warning(
                "Failed to fetch stored addresses for peer %s: %s", dest_info.peer_id, e
            )

        # Get validated stored p2p-circuit addrs
        circuit_addrs = []
        for ma in stored_addrs:
            try:
                _, target_peer_id = self.parse_circuit_ma(ma)
                if target_peer_id == dest_info.peer_id:
                    circuit_addrs.append(ma)
            except ValueError:
                continue

        # Try stored addresses first (optimization from origin/main)
        for ma in circuit_addrs:
            # Start timing for this specific connection attempt
            attempt_start_time = trio.current_time()
            try:
                logger.debug(
                    "Trying stored circuit multiaddr %s for peer %s",
                    ma,
                    dest_info.peer_id,
                )
                conn = await self._dial_via_circuit_addr(ma, dest_info)
                if conn:
                    logger.debug("Connected via stored circuit addr %s", ma)
                    # Record successful connection attempt
                    relay_peer_id = self._extract_relay_id_from_ma(ma)
                    latency_ms = (trio.current_time() - attempt_start_time) * 1000
                    self.performance_tracker.record_connection_attempt(
                        relay_id=relay_peer_id,
                        latency_ms=latency_ms,
                        success=True,
                    )
                    # Record circuit opened
                    self.performance_tracker.record_circuit_opened(relay_peer_id)
                    # Store multiaddrs for future use
                    self._store_multiaddrs(dest_info, relay_peer_id)
                    # conn is already a TrackedRawConnection from _dial_via_circuit_addr
                    return conn
                logger.debug("Dial via %s returned None", ma)
            except Exception as e:
                logger.debug("Stored circuit addr failed (%s): %s", ma, e)
                # Record failure in performance tracker
                try:
                    relay_peer_id = self._extract_relay_id_from_ma(ma)
                    latency_ms = (trio.current_time() - attempt_start_time) * 1000
                    self.performance_tracker.record_connection_attempt(
                        relay_id=relay_peer_id,
                        latency_ms=latency_ms,
                        success=False,
                    )
                except Exception:
                    pass  # Ignore errors in tracking

        # If no specific relay is provided, try to find one
        if relay_info is None:
            selected_relay = await self._select_relay(dest_info)
            if not selected_relay:
                raise ConnectionError("No suitable relay found")
            relay_peer_id = selected_relay
            relay_info = self.host.get_peerstore().peer_info(relay_peer_id)
        else:
            relay_peer_id = relay_info.peer_id

        await self.host.connect(relay_info)

        # Get a stream to the relay
        try:
            logger.debug(
                "Opening stream to relay %s with protocol %s",
                relay_peer_id,
                PROTOCOL_ID,
            )
            relay_stream = await self.host.new_stream(relay_peer_id, [PROTOCOL_ID])
            if not relay_stream:
                raise ConnectionError(f"Could not open stream to relay {relay_peer_id}")
            logger.debug("Successfully opened stream to relay %s", relay_peer_id)
        except Exception as e:
            logger.error("Failed to open stream to relay %s: %s", relay_peer_id, str(e))
            raise ConnectionError(
                f"Could not open stream to relay {relay_peer_id}: {str(e)}"
            )

        try:
            # First try to make a reservation if enabled
            if self.config.enable_client:
                success = await self._make_reservation(relay_stream, relay_peer_id)
                if not success:
                    logger.warning(
                        "Failed to make reservation with relay %s", relay_peer_id
                    )
            # Create signed peer record to send with the HOP message
            envelope_bytes, _ = env_to_send_in_RPC(self.host)

            # Send HOP CONNECT message
            connect_msg = HopMessage(
                type=HopMessage.CONNECT,
                peer=dest_info.peer_id.to_bytes(),
                senderRecord=envelope_bytes,
            )
            await relay_stream.write(connect_msg.SerializeToString())

            # Read response with timeout
            with trio.fail_after(STREAM_READ_TIMEOUT):
                resp_bytes = await relay_stream.read(1024)
                resp = HopMessage()
                resp.ParseFromString(resp_bytes)

            # Get destination peer SPR from the relay's response and validate it
            if resp.HasField("senderRecord"):
                if not maybe_consume_signed_record(resp, self.host, dest_info.peer_id):
                    logger.warning(
                        "Received an invalid senderRecord from relay, "
                        "but continuing connection"
                    )
                    # Don't fail the connection - the senderRecord is optional
                    # and the relay might not have the destination's signed peer record

            # Access status attributes directly
            status_code = getattr(resp.status, "code", StatusCode.OK)
            status_msg = getattr(resp.status, "message", "Unknown error")

            if status_code != StatusCode.OK:
                raise ConnectionError(f"Relay connection failed: {status_msg}")

            # Record successful connection attempt
            latency_ms = (trio.current_time() - connection_start_time) * 1000
            self.performance_tracker.record_connection_attempt(
                relay_id=relay_peer_id,
                latency_ms=latency_ms,
                success=True,
            )

            # Record circuit opened
            self.performance_tracker.record_circuit_opened(relay_peer_id)

            # Store multiaddrs for future use
            self._store_multiaddrs(dest_info, relay_peer_id)

            # Create raw connection from stream and wrap it to track closure
            raw_conn = RawConnection(stream=relay_stream, initiator=True)
            return TrackedRawConnection(
                wrapped=raw_conn,
                relay_id=relay_peer_id,
                tracker=self.performance_tracker,
            )

        except Exception as e:
            # Record failed connection attempt
            latency_ms = (trio.current_time() - connection_start_time) * 1000
            self.performance_tracker.record_connection_attempt(
                relay_id=relay_peer_id,
                latency_ms=latency_ms,
                success=False,
            )
            await relay_stream.close()
            raise ConnectionError(f"Failed to establish relay connection: {str(e)}")

    def parse_circuit_ma(
        self, ma: multiaddr.Multiaddr
    ) -> tuple[multiaddr.Multiaddr, ID]:
        """
        Parse a /p2p-circuit/p2p/<targetPeerID> path from a relay Multiaddr.

        Returns:
            relay_ma: Multiaddr to the relay
            target_peer_id: ID of the target peer

        Raises:
            ValueError: if the Multiaddr is not a valid circuit address

        """
        parts = ma.items()

        if len(parts) < 2:
            raise ValueError(f"Invalid circuit Multiaddr, too short: {ma}")

        proto_name, _ = parts[-2]
        if proto_name.name != "p2p-circuit":
            raise ValueError(f"Missing /p2p-circuit in Multiaddr: {ma}")

        proto_name, val = parts[-1]
        if proto_name.name != "p2p":
            raise ValueError(f"Missing /p2p/<peerID> at the end: {ma}")

        try:
            if isinstance(val, ID):
                target_peer_id = val
            else:
                target_peer_id = ID.from_string(val)
        except Exception as e:
            raise ValueError(f"Invalid peer ID in circuit Multiaddr: {val}") from e

        relay_parts = parts[:-2]
        relay_ma_str = "/".join(
            f"{p[0].name}/{p[1]}" for p in relay_parts if p[1] is not None
        )
        relay_ma = (
            multiaddr.Multiaddr(relay_ma_str)
            if relay_ma_str
            else multiaddr.Multiaddr("/")
        )

        return relay_ma, target_peer_id

    def _store_multiaddrs(self, peer_info: PeerInfo, relay_peer_id: ID) -> None:
        """
        Store all /p2p-circuit addresses for a peer in the peerstore,
        based on the relay's addresses.
        """
        try:
            relay_addrs = self.host.get_peerstore().addrs(relay_peer_id)
            if not relay_addrs:
                return

            peer_store = self.host.get_peerstore()
            for relay_ma in relay_addrs:
                if not isinstance(relay_ma, multiaddr.Multiaddr):
                    continue

                # Construct /p2p-circuit address
                circuit_ma = relay_ma.encapsulate(
                    multiaddr.Multiaddr("/p2p-circuit")
                ).encapsulate(multiaddr.Multiaddr(f"/p2p/{peer_info.peer_id}"))

                peer_store.add_addrs(peer_info.peer_id, [circuit_ma], ttl=2**31 - 1)
                logger.debug(
                    "Stored relay circuit multiaddr %s for peer %s",
                    circuit_ma,
                    peer_info.peer_id,
                )

        except Exception as e:
            logger.error(
                "Failed to store relay multiaddrs for peer %s: %s", peer_info.peer_id, e
            )

    async def _dial_via_circuit_addr(
        self, circuit_ma: multiaddr.Multiaddr, peer_info: PeerInfo
    ) -> IRawConnection:
        """
        Dial using a stored /p2p-circuit multiaddr.

        circuit_ma looks like: <relay-ma>/p2p-circuit/p2p/<target-peer-id>
        We extract the relay multiaddr (everything before /p2p-circuit), dial the relay,
        and issue a HOP CONNECT to the target peer.
        """
        ma_str = str(circuit_ma)
        idx = ma_str.find("/p2p-circuit")
        if idx == -1:
            raise ConnectionError("Not a p2p-ciruit multiaddr")

        relay_ma_str = ma_str[:idx]  # everything before /p2p-circuit
        relay_ma = multiaddr.Multiaddr(relay_ma_str)
        relay_peer_id_str = relay_ma.value_for_protocol("p2p")
        if not relay_peer_id_str:
            raise ConnectionError("Relay multiaddr missing peer id")

        relay_peer_id = ID.from_string(relay_peer_id_str)

        # open stream to the relay and request hop connect
        relay_stream = await self.host.new_stream(relay_peer_id, [PROTOCOL_ID])
        if not relay_stream:
            raise ConnectionError(f"Could not open stream to relay {relay_peer_id}")

        try:
            hop_msg = HopMessage(
                type=HopMessage.CONNECT,
                peer=peer_info.peer_id.to_bytes(),
            )
            await relay_stream.write(hop_msg.SerializeToString())

            resp_bytes = await relay_stream.read()
            resp = HopMessage()
            resp.ParseFromString(resp_bytes)

            status_code = getattr(resp.status, "code", StatusCode.OK)
            status_msg = getattr(resp.status, "message", "Unknown error")

            if status_code != StatusCode.OK:
                await relay_stream.close()
                raise ConnectionError(f"Relay connection failed: {status_msg}")

            # Wrap in TrackedRawConnection for tracking
            raw_conn = RawConnection(stream=relay_stream, initiator=True)
            return TrackedRawConnection(
                wrapped=raw_conn,
                relay_id=relay_peer_id,
                tracker=self.performance_tracker,
            )

        except Exception:
            await relay_stream.close()
            raise

    async def _select_relay(self, peer_info: PeerInfo) -> ID | None:
        """
        Select an appropriate relay for the given peer.

        Selection priority:
        1. Performance-tracked relays from discovery (with reservations prioritized)
        2. DHT-discovered relays (if enabled and no discovery relays available)
        3. Round-robin among equal-scored relays

        Uses performance tracking to select the best relay based on:
        - Connection latency (lower is better)
        - Active circuit count (fewer is better)
        - Success rate (higher is better)

        Parameters
        ----------
        peer_info : PeerInfo
            The peer to connect to

        Returns
        -------
        ID | None
            Chosen relay peer ID or None if no suitable relay is found.

        """
        if not self.client_config.enable_auto_relay:
            logger.warning("Auto-relay disabled, skipping relay selection")
            return None

        attempts = 0
        while attempts < self.client_config.max_auto_relay_attempts:
            # Step 1: Get relays from discovery
            relays = self.discovery.get_relays() or []

            # Step 2: If no relays from discovery, try DHT (from origin/main)
            if not relays and self.dht:
                discovered = await self.discover_peers(
                    peer_info.peer_id.to_bytes(), max_results=TOP_N
                )
                for p in discovered:
                    if p.peer_id.to_string() not in {r.to_string() for r in relays}:
                        relays.append(p.peer_id)

            if not relays:
                backoff = min(2**attempts, 10)
                await trio.sleep(backoff)
                attempts += 1
                continue

            # Step 3: Prioritize relays with active reservations (from HEAD)
            relays_with_reservations = []
            other_relays = []

            for relay_id in relays:
                relay_info = self.discovery.get_relay_info(relay_id)
                if relay_info and relay_info.has_reservation:
                    relays_with_reservations.append(relay_id)
                else:
                    other_relays.append(relay_id)

            # Step 4: Use performance tracker to select best relay (from HEAD)
            candidate_list = (
                relays_with_reservations if relays_with_reservations else other_relays
            )

            if candidate_list:
                selected_relay = self.performance_tracker.select_best_relay(
                    available_relays=candidate_list,
                    require_reservation=False,  # Already filtered
                    relay_info_getter=self.discovery.get_relay_info,
                )

                if selected_relay:
                    # Step 5: Round-robin for equal scores (from HEAD)
                    best_score = self.performance_tracker.get_relay_score(
                        selected_relay
                    )
                    equal_score_relays = [
                        r
                        for r in candidate_list
                        if self.performance_tracker.get_relay_score(r) == best_score
                        and best_score != float("inf")
                    ]

                    if len(equal_score_relays) > 1:
                        async with self._relay_counter_lock:
                            index = self.relay_counter % len(equal_score_relays)
                            selected_relay = equal_score_relays[index]
                            self.relay_counter += 1

                    return selected_relay

            backoff = min(2**attempts, 10)
            await trio.sleep(backoff)
            attempts += 1

        logger.warning(
            "No suitable relay found after %d attempts",
            self.client_config.max_auto_relay_attempts,
        )
        return None

    def _extract_relay_id_from_ma(self, ma: multiaddr.Multiaddr) -> ID:
        """Extract relay peer ID from a circuit multiaddr."""
        relay_ma, _ = self.parse_circuit_ma(ma)
        relay_peer_id_str = relay_ma.value_for_protocol("p2p")
        if not relay_peer_id_str:
            raise ValueError("Relay multiaddr missing peer id")
        return ID.from_string(relay_peer_id_str)

    async def discover_peers(self, key: bytes, max_results: int = 5) -> list[PeerInfo]:
        if not self.dht:
            return []

        found_peers: list[PeerInfo] = []

        # 1. Use the routing table of the DHT
        closest_ids = self.dht.routing_table.find_local_closest_peers(key, 20)
        for peer_id in closest_ids:
            if self.dht and peer_id == self.dht.local_peer_id:
                continue
            if len(found_peers) >= max_results:
                break
            assert self.dht is not None
            peer_info = await self.dht.find_peer(peer_id)
            if peer_info:
                found_peers.append(peer_info)

        return found_peers[:max_results]

    async def _is_relay_available(self, relay_peer_id: ID) -> bool:
        """Check if the relay is currently reachable."""
        try:
            # try opening a shortlived stream
            stream = await self.host.new_stream(relay_peer_id, [PROTOCOL_ID])
            await stream.close()
            return True
        except Exception:
            return False

    async def _measure_relay(
        self, relay_id: ID, scored_relays: list[tuple[ID, float]]
    ) -> None:
        metrics = self._relay_metrics.setdefault(
            relay_id, {"latency": 0, "failures": 0, "last_seen": 0}
        )
        start = time.monotonic()
        available = await self._is_relay_available(relay_id)
        latency = time.monotonic() - start

        if not available:
            metrics["failures"] += 1
            return

        metrics.update(
            {
                "latency": latency,
                "failures": max(0.0, metrics["failures"] - 1),
                "last_seen": time.time(),
            }
        )

        score = (
            1000
            - (metrics["failures"] * 10)
            - (latency * 100)
            - ((time.time() - metrics["last_seen"]) * 0.1)
        )
        scored_relays.append((relay_id, score))

    async def reserve(
        self, stream: INetStream, relay_peer_id: ID, nursery: trio.Nursery
    ) -> bool:
        """
        Public method to create a reservation and start refresher if needed.
        """
        success = await self._make_reservation(stream, relay_peer_id)
        if not success:
            return False

        # Start refresher if this is the first reservation
        if not self._refreshing:
            self._refreshing = True
            nursery.start_soon(self._refresh_reservations_worker)
        return True

    async def _make_reservation(
        self,
        stream: INetStream,
        relay_peer_id: ID,
    ) -> bool:
        """
        Make a reservation with a relay.

        Parameters
        ----------
        stream : INetStream
            Stream to the relay
        relay_peer_id : ID
            The relay's peer ID

        Returns
        -------
        bool
            True if reservation was successful

        """
        try:
            # Create signed envelope for the reservation request to relay
            envelope_bytes, _ = env_to_send_in_RPC(self.host)
            # Send reservation request
            reserve_msg = HopMessage(
                type=HopMessage.RESERVE,
                peer=self.host.get_id().to_bytes(),
                senderRecord=envelope_bytes,
            )

            try:
                await stream.write(reserve_msg.SerializeToString())
                logger.debug("Successfully sent reservation request")
            except Exception as e:
                logger.error("Failed to send reservation request: %s", str(e))
                raise

            # Read response with timeout
            with trio.fail_after(STREAM_READ_TIMEOUT):
                try:
                    resp_bytes = await stream.read(1024)
                    logger.debug(
                        "Received reservation response: %d bytes", len(resp_bytes)
                    )
                    resp = HopMessage()
                    resp.ParseFromString(resp_bytes)
                except Exception as e:
                    logger.error(
                        "Failed to read/parse reservation response: %s", str(e)
                    )
                    raise

            if resp.HasField("senderRecord"):
                if not maybe_consume_signed_record(resp, self.host, relay_peer_id):
                    logger.warning(
                        "Received an invalid senderRecord from relay, "
                        "but continuing reservation"
                    )
                    # Don't fail the reservation - the senderRecord is optional

            # Access status attributes directly
            status_code = getattr(resp.status, "code", StatusCode.OK)
            status_msg = getattr(resp.status, "message", "Unknown error")
            expires = getattr(resp.reservation, "expire", 0)

            logger.debug(
                "Reservation response: code=%s, message=%s", status_code, status_msg
            )

            if status_code != StatusCode.OK:
                logger.warning(
                    "Reservation failed with relay %s: %s",
                    relay_peer_id,
                    status_msg,
                )
                return False

            self._reservations[relay_peer_id] = expires
            logger.info("Reserved peer %s (ttl=%.1fs)", relay_peer_id, expires)

            return True

        except Exception as e:
            logger.error("Error making reservation: %s", str(e))
            return False

    async def _refresh_reservations_worker(self) -> None:
        """Periodically refresh all active reservations."""
        logger.info("Started reservation refresh loop")
        try:
            while self._reservations:
                now = time.time()
                expired = [
                    relay_peer_id
                    for relay_peer_id, exp in self._reservations.items()
                    if exp <= now
                ]

                # Remove expired reservations
                for relay_peer_id in expired:
                    logger.info("Reservation expired for peer %s", relay_peer_id)
                    del self._reservations[relay_peer_id]

                to_refresh = [
                    relay_peer_id
                    for relay_peer_id, exp in self._reservations.items()
                    if exp - now <= RESERVATION_REFRESH_MARGIN
                ]

                for relay_peer_id in to_refresh:
                    try:
                        # Open a fresh stream per refresh
                        stream = await self.host.new_stream(
                            relay_peer_id, [PROTOCOL_ID]
                        )
                        success = await self._make_reservation(stream, relay_peer_id)
                        await stream.close()
                        if success:
                            logger.info(
                                "Refreshed reservation for relay %s", relay_peer_id
                            )
                        else:
                            logger.warning(
                                "Failed to refresh reservation for relay %s",
                                relay_peer_id,
                            )
                    except Exception as e:
                        logger.error(
                            "Error refreshing reservation for relay %s: %s",
                            relay_peer_id,
                            str(e),
                        )

                # Calculate next wake-up dynamically
                now = time.time()
                next_exp = min(
                    self._reservations.values(),
                    default=now + RESERVATION_REFRESH_INTERVAL,
                )
                sleep_time = max(0.0, next_exp - now - RESERVATION_REFRESH_MARGIN)
                await trio.sleep(sleep_time)

        except trio.Cancelled:
            self._refreshing = False
            logger.info("Reservation refresher cancelled")
        finally:
            self._refreshing = False
            logger.info("Stopped reservation refresher")

    def create_listener(self, handler_function: THandler) -> IListener:
        """
        Create a listener on the transport.

        Parameters
        ----------
        handler_function : THandler
            A function that is called when a new connection is received.
            The function should accept a connection (that implements the
            connection interface) as its argument.

        Returns
        -------
        IListener
            A listener instance.

        """
        return CircuitV2Listener(
            self.host, handler_function, self.protocol, self.config
        )


class CircuitV2Listener(Service, IListener):
    """Listener for incoming relay connections."""

    def __init__(
        self,
        host: IHost,
        handler_function: THandler,
        protocol: CircuitV2Protocol,
        config: RelayConfig,
    ) -> None:
        """
        Initialize the Circuit v2 listener.

        Parameters
        ----------
        host : IHost
            The libp2p host this listener is running on
        handler_function: Callable[[ReadWriteCloser], Awaitable[None]]
            The handler function for new connections
        protocol : CircuitV2Protocol
            The Circuit v2 protocol instance
        config : RelayConfig
            Relay configuration

        """
        super().__init__()
        self.host = host
        self.protocol = protocol
        self.config = config
        self.multiaddrs: list[
            multiaddr.Multiaddr
        ] = []  # Store multiaddrs as Multiaddr objects
        self.handler_function = handler_function

    async def handle_incoming_connection(
        self,
        stream: INetStream,
    ) -> RawConnection:
        """
        Handle an incoming relay connection.

        Parameters
        ----------
        stream : INetStream
            The incoming stream
        remote_peer_id : ID
            The remote peer's ID

        Returns
        -------
        RawConnection
            The established connection

        Raises
        ------
        ConnectionError
            If the connection cannot be established

        """
        if not self.config.enable_stop:
            raise ConnectionError("Stop role is not enabled")

        try:
            # Read STOP message
            msg_bytes = await stream.read()
            stop_msg = StopMessage()
            stop_msg.ParseFromString(msg_bytes)

            if stop_msg.type != StopMessage.CONNECT:
                raise ConnectionError("Invalid STOP message type")

            # Create raw connection
            return RawConnection(stream=stream, initiator=False)

        except Exception as e:
            await stream.close()
            raise ConnectionError(f"Failed to handle incoming connection: {str(e)}")

    async def run(self) -> None:
        """Run the listener service."""
        if not self.config.enable_stop:
            logger.warning(
                "Stop role is disabled, listener will not process incoming connections"
            )
            return

        async def stream_handler(stream: INetStream) -> None:
            """Handle incoming streams for the Circuit v2 protocol."""
            stream_with_peer_id = cast(INetStreamWithExtras, stream)
            remote_peer_id = stream_with_peer_id.get_remote_peer_id()

            try:
                connection = await self.handle_incoming_connection(stream)

                await self.handler_function(connection)
            except ConnectionError as e:
                logger.error(
                    "Failed to handle incoming connection from %s: %s",
                    remote_peer_id,
                    str(e),
                )
                await stream.close()
            except Exception as e:
                logger.error(
                    "Unexpected error handling stream from %s: %s",
                    remote_peer_id,
                    str(e),
                )
                await stream.close()

        self.host.set_stream_handler(PROTOCOL_ID, stream_handler)
        try:
            await self.manager.wait_finished()
        finally:
            logger.debug("CircuitV2Listener stopped")

    async def listen(self, maddr: multiaddr.Multiaddr, nursery: trio.Nursery) -> bool:
        """
        Start listening on the given multiaddr.

        Parameters
        ----------
        maddr : multiaddr.Multiaddr
            The multiaddr to listen on
        nursery : trio.Nursery
            The nursery to run tasks in

        Returns
        -------
        bool
            True if listening successfully started

        """
        # Convert string to Multiaddr if needed
        addr = (
            maddr
            if isinstance(maddr, multiaddr.Multiaddr)
            else multiaddr.Multiaddr(maddr)
        )
        self.multiaddrs.append(addr)
        return True

    def get_addrs(self) -> tuple[multiaddr.Multiaddr, ...]:
        """
        Get the listening addresses.

        Returns
        -------
        tuple[multiaddr.Multiaddr, ...]
            Tuple of listening multiaddresses

        """
        return tuple(self.multiaddrs)

    async def close(self) -> None:
        """Close the listener."""
        self.multiaddrs.clear()
        await self.manager.stop()
