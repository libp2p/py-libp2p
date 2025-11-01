"""
Transport implementation for Circuit Relay v2.

This module implements the transport layer for Circuit Relay v2,
allowing peers to establish connections through relay nodes.
"""

from collections.abc import Awaitable, Callable
import logging
import time
from typing import cast

import multiaddr
import trio

from libp2p.abc import (
    IHost,
    IListener,
    INetStream,
    ITransport,
    ReadWriteCloser,
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
from .protocol import (
    PROTOCOL_ID,
    CircuitV2Protocol,
    INetStreamWithExtras,
)
from .protocol_buffer import (
    StatusCode,
)

logger = logging.getLogger("libp2p.relay.circuit_v2.transport")
TOP_N = 3
RESERVATION_REFRESH_INTERVAL = 10 # seconds
RESERVATION_REFRESH_MARGIN = 30 # seconds

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
        self._last_relay_index = -1
        self._relay_list = []
        self._relay_metrics: dict[ID, dict[str, float | int]] = {}
        self._reservations: dict[ID, float] = {}
        self._refreshing = False
        self.dht: KadDHT | None = None
        if config.enable_dht_discovery:
            self.dht = KadDHT(host, DHTMode.CLIENT)

    async def dial(
        self,
        maddr: multiaddr.Multiaddr,
    ) -> RawConnection:
        """
        Dial a peer using the multiaddr.

        Parameters
        ----------
        maddr : multiaddr.Multiaddr
            The multiaddr to dial

        Returns
        -------
        RawConnection
            The established connection

        Raises
        ------
        ConnectionError
            If the connection cannot be established

        """
        # Extract peer ID from multiaddr - P_P2P code is 0x01A5 (421)
        peer_id_str = maddr.value_for_protocol("p2p")
        if not peer_id_str:
            raise ConnectionError("Multiaddr does not contain peer ID")

        peer_id = ID.from_base58(peer_id_str)
        peer_info = PeerInfo(peer_id, [maddr])

        # Use the internal dial_peer_info method
        return await self.dial_peer_info(peer_info)

    async def dial_peer_info(
        self,
        peer_info: PeerInfo,
        *,
        relay_peer_id: ID | None = None,
    ) -> RawConnection:
        """
        Dial a peer through a relay.

        Parameters
        ----------
        peer_info : PeerInfo
            The peer to dial
        relay_peer_id : Optional[ID], optional
            Optional specific relay peer to use

        Returns
        -------
        RawConnection
            The established connection

        Raises
        ------
        ConnectionError
            If the connection cannot be established

        """
        # Prefer stored /p2p-circuit addrs from peerstore
        # Try first to read addresses from peerstore
        peer_store = self.host.get_peerstore()
        stored_addrs = peer_store.addrs(peer_info.peer_id)

        # Get validated stored p2p-circuit addrs
        circuit_addrs = []
        for ma in stored_addrs:
            try:
                _, target_peer_id = self.parse_circuit_ma(ma)
                if target_peer_id == peer_info.peer_id:
                    circuit_addrs.append(ma)
            except ValueError:
                continue

        for ma in circuit_addrs:
            try:
                logger.debug(
                    "Trying stored circuit multiaddr %s for peer %s",
                    ma,
                    peer_info.peer_id
                )
                conn = await self._dial_via_circuit_addr(ma, peer_info)
                if conn:
                    logger.debug("Connected via stored circuit addr %s", ma)
                    return conn
                logger.debug("Dial via %s returned None", ma)
            except Exception as e:
                logger.debug("Stored circuit addr failed (%s): %s", ma, e)

        # If no specific relay is provided, try to find one
        if relay_peer_id is None:
            relay_peer_id = await self._select_relay(peer_info)
            if not relay_peer_id:
                raise ConnectionError("No suitable relay found")

        # Get a stream to the relay
        relay_stream = await self.host.new_stream(relay_peer_id, [PROTOCOL_ID])
        if not relay_stream:
            raise ConnectionError(f"Could not open stream to relay {relay_peer_id}")

        try:
            # First try to make a reservation if enabled
            if self.config.enable_client:
                async with trio.open_nursery() as nursery:
                    success = await self.reserve(relay_stream, relay_peer_id, nursery)
                    if not success:
                        logger.warning(
                            "Failed to make reservation with relay %s", relay_peer_id
                        )

            # Send HOP CONNECT message
            hop_msg = HopMessage(
                type=HopMessage.CONNECT,
                peer=peer_info.peer_id.to_bytes(),
            )
            await relay_stream.write(hop_msg.SerializeToString())

            # Read response
            resp_bytes = await relay_stream.read()
            resp = HopMessage()
            resp.ParseFromString(resp_bytes)

            # Access status attributes directly
            status_code = getattr(resp.status, "code", StatusCode.OK)
            status_msg = getattr(resp.status, "message", "Unknown error")

            if status_code != StatusCode.OK:
                raise ConnectionError(f"Relay connection failed: {status_msg}")

            # Create raw connection from stream
            self._store_multiaddrs(peer_info, relay_peer_id)
            return RawConnection(stream=relay_stream, initiator=True)

        except Exception as e:
            await relay_stream.close()
            raise ConnectionError(f"Failed to establish relay connection: {str(e)}")

    def parse_circuit_ma(
            self,
            ma: multiaddr.Multiaddr
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
                target_peer_id = ID.from_base58(val)
        except Exception as e:
            raise ValueError(f"Invalid peer ID in circuit Multiaddr: {val}") from e

        relay_parts = parts[:-2]
        relay_ma_str = "/".join(
            f"{p[0].name}/{p[1]}"
            for p in relay_parts
            if p[1] is not None
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
                circuit_ma = (
                    relay_ma
                        .encapsulate(multiaddr.Multiaddr("/p2p-circuit"))
                        .encapsulate(multiaddr.Multiaddr(f"/p2p/{peer_info.peer_id}"))
                )

                peer_store.add_addrs(peer_info.peer_id, [circuit_ma], ttl=2**31-1)
                logger.debug(
                    "Stored relay circuit multiaddr %s for peer %s",
                    circuit_ma,
                    peer_info.peer_id
                )

        except Exception as e:
            logger.error(
                "Failed to store relay multiaddrs for peer %s: %s",
                peer_info.peer_id,
                e
            )


    async def _dial_via_circuit_addr(
            self,
            circuit_ma: multiaddr.Multiaddr,
            peer_info: PeerInfo
    ) -> RawConnection:
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

        relay_ma_str = ma_str[:idx] # everything before /p2p-circuit
        relay_ma = multiaddr.Multiaddr(relay_ma_str)
        relay_peer_id_str = relay_ma.value_for_protocol("p2p")
        if not relay_peer_id_str:
            raise ConnectionError("Relay multiaddr missing peer id")

        relay_peer_id = ID.from_base58(relay_peer_id_str)

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

            return RawConnection(stream=relay_stream, initiator=True)

        except Exception:
            await relay_stream.close()
            raise

    async def _select_relay(self, peer_info: PeerInfo) -> ID | None:
        """
        Select an appropriate relay for the given peer.

        Selection priority:
        1. Stored relays in _relay_list.
        2. Relays discovered dynamically via DHT.
        3. Measure, score, and pick top N relays round-robin.

        Returns
        -------
        ID | None
            Chosen relay peer ID or None if no suitable relay is found.

        """
        if not self.client_config.enable_auto_relay:
            logger.warning("Auto-relay disabled, skipping relay selection")
            return None

        for attempt in range(self.client_config.max_auto_relay_attempts):
            # --- Step 1: Use stored relays if available ---
            if not self._relay_list:
                # Fetch relays from discovery
                relays = self.discovery.get_relays() or []
                seen = {r.to_string() for r in self._relay_list}
                for r in relays:
                    if r.to_string() not in seen:
                        self._relay_list.append(r)
                        seen.add(r.to_string())

                # --- Step 2: Fall back to DHT if still empty ---
                if not self._relay_list and self.dht:
                    discovered = await self.discover_peers(
                        peer_info.peer_id.to_bytes(),
                        max_results=TOP_N
                    )
                    for p in discovered:
                        if p.peer_id.to_string() not in {
                            r.to_string()
                            for r in self._relay_list
                        }:
                            self._relay_list.append(p.peer_id)

            if not self._relay_list:
                backoff = min(2 ** attempt, 10)
                await trio.sleep(backoff)
                continue

            # --- Step 3: Measure relays concurrently ---
            scored_relays: list[tuple[ID, float]] = []
            async with trio.open_nursery() as nursery:
                for relay_id in list(self._relay_list):
                    nursery.start_soon(self._measure_relay, relay_id, scored_relays)

            if not scored_relays:
                backoff = min(2 ** attempt, 10)
                await trio.sleep(backoff)
                continue

            # --- Step 4: Filter by minimum score ---
            filtered = [
                (rid, score) for rid, score in scored_relays
                if score >= self.client_config.min_relay_score
            ]
            if not filtered:
                backoff = min(2 ** attempt, 10)
                await trio.sleep(backoff)
                continue

            # --- Step 5: Sort top relays ---
            filtered.sort(key=lambda x: (x[1], x[0].to_string()), reverse=True)
            top_relays = [rid for rid, _ in filtered[:TOP_N]]
            if not top_relays:
                backoff = min(2 ** attempt, 10)
                await trio.sleep(backoff)
                continue

            # --- Step 6: Round-robin selection ---
            if self._last_relay_index == -1:
                self._last_relay_index = 0
            else:
                self._last_relay_index = (self._last_relay_index + 1) % len(top_relays)
            chosen = top_relays[self._last_relay_index]

            # Ensure metrics exist
            if chosen not in self._relay_metrics:
                self._relay_metrics[chosen] = {
                    "latency": 0,
                    "failures": 0,
                    "last_seen": 0
                }

            logger.debug(
                "Selected relay %s from top %d candidates (lat=%.3fs)",
                chosen,
                len(top_relays),
                self._relay_metrics[chosen].get("latency", 0),
            )
            return chosen

        logger.warning(
            "No suitable relay found after %d attempts",
            self.client_config.max_auto_relay_attempts
        )
        return None

    async def discover_peers(self, key: bytes, max_results: int = 5) -> list[PeerInfo]:
        if not self.dht:
            return []

        found_peers: list[PeerInfo] = []

        # 1. Use the routing table of the DHT
        closest_ids = self.dht.routing_table.find_local_closest_peers(key, 20)
        for peer_id in closest_ids:
            if peer_id == self.dht.local_peer_id:
                continue
            if len(found_peers) >= max_results:
                break
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

    async def _measure_relay(self, relay_id: ID, scored_relays: list):
        metrics = self._relay_metrics.setdefault(
            relay_id, {
                "latency": 0,
                "failures": 0,
                "last_seen": 0
            }
        )
        start = time.monotonic()
        available = await self._is_relay_available(relay_id)
        latency = time.monotonic() - start

        if not available:
            metrics["failures"] += 1
            return

        metrics.update({
            "latency": latency,
            "failures": max(0, metrics["failures"] - 1),
            "last_seen": time.time()
        })

        score = (
            1000
            - (metrics["failures"] * 10)
            - (latency * 100)
            - ((time.time() - metrics["last_seen"]) * 0.1)
        )
        scored_relays.append((relay_id, score))

    async def reserve(
            self,
            stream: INetStream,
            relay_peer_id: ID,
            nursery: trio.Nursery
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
            nursery.start_soon(
                self._refresh_reservations_worker
            )
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
            # Send reservation request
            reserve_msg = HopMessage(
                type=HopMessage.RESERVE,
                peer=self.host.get_id().to_bytes(),
            )
            await stream.write(reserve_msg.SerializeToString())

            # Read response
            resp_bytes = await stream.read()
            resp = HopMessage()
            resp.ParseFromString(resp_bytes)

            # Access status attributes directly
            status_code = getattr(resp.status, "code", StatusCode.OK)
            status_msg = getattr(resp.status, "message", "Unknown error")
            expires = getattr(resp.reservation, "expire", 0)

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
                    relay_peer_id for relay_peer_id,
                    exp in self._reservations.items()
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
                            relay_peer_id,
                            [PROTOCOL_ID]
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
                                relay_peer_id
                            )
                  except Exception as e:
                      logger.error(
                            "Error refreshing reservation for relay %s: %s",
                            relay_peer_id, str(e)
                        )

                # Calculate next wake-up dynamically
                now = time.time()
                next_exp = min(
                    self._reservations.values(),
                    default=now + RESERVATION_REFRESH_INTERVAL
                )
                sleep_time = max(0, next_exp - now - RESERVATION_REFRESH_MARGIN)
                await trio.sleep(sleep_time)

        except trio.Cancelled:
            self._refreshing = False
            logger.info("Reservation refresher cancelled")
        finally:
            self._refreshing = False
            logger.info("Stopped reservation refresher")



    def create_listener(
        self,
        handler_function: Callable[[ReadWriteCloser], Awaitable[None]],
    ) -> IListener:
        """
        Create a listener for incoming relay connections.

        Parameters
        ----------
        handler_function : Callable[[ReadWriteCloser], Awaitable[None]]
            The handler function for new connections

        Returns
        -------
        IListener
            The created listener

        """
        return CircuitV2Listener(
            self.host,
            handler_function,
            self.protocol,
            self.config
        )


class CircuitV2Listener(Service, IListener):
    """Listener for incoming relay connections."""

    def __init__(
        self,
        host: IHost,
        handler_function: Callable[[ReadWriteCloser], Awaitable[None]],
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
        remote_peer_id: ID,
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
                connection = await self.handle_incoming_connection(
                    stream, remote_peer_id
                )

                await self.handler_function(connection)
            except ConnectionError as e:
                logger.error(
                    "Failed to handle incoming connection from %s: %s",
                    remote_peer_id, str(e)
                )
                await stream.close()
            except Exception as e:
                logger.error(
                    "Unexpected error handling stream from %s: %s",
                    remote_peer_id, str(e)
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
