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
                success = await self._make_reservation(relay_stream, relay_peer_id)
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
            return RawConnection(stream=relay_stream, initiator=True)

        except Exception as e:
            await relay_stream.close()
            raise ConnectionError(f"Failed to establish relay connection: {str(e)}")

    async def _select_relay(self, peer_info: PeerInfo) -> ID | None:
        """
        Select an appropriate relay for the given peer.

        - Gather relays (preserve insertion order, dedupe by to_string()).
        - Measure relays concurrently to collect scores.
        - Take top TOP_N relays by score (desc, tie-break by to_string()).
        - Pick one from top list using round-robin across invocations.

        Returns:
            Selected relay ID or None if none found.

        """
        if not self.client_config.enable_auto_relay:
            logger.warning("Auto-relay disabled, skipping relay selection")
            return None

        for attempt in range(self.client_config.max_auto_relay_attempts):
            # Fetch relays if _relay_list is empty — preserve order and dedupe
            if not self._relay_list:
                relays = self.discovery.get_relays() or []
                # preserve current order and append new ones (dedupe by to_string)
                seen = {r.to_string() for r in self._relay_list}
                for r in relays:
                    if r.to_string() not in seen:
                        self._relay_list.append(r)
                        seen.add(r.to_string())

            if not self._relay_list:
                backoff = min(2 ** attempt, 10)
                await trio.sleep(backoff)
                continue

            # Measure all relays concurrently.
            # scored_relays will be filled by _measure_relay.
            scored_relays: list[tuple[ID, float]] = []
            async with trio.open_nursery() as nursery:
                for relay_id in list(self._relay_list):
                    nursery.start_soon(self._measure_relay, relay_id, scored_relays)

            # If no scored relays, backoff and retry
            if not scored_relays:
                backoff = min(2 ** attempt, 10)
                await trio.sleep(backoff)
                continue

            # Filter by minimum score
            filtered = [
                (rid, score) for (rid, score)
                in scored_relays
                if score >= self.client_config.min_relay_score
            ]
            if not filtered:
                backoff = min(2 ** attempt, 10)
                await trio.sleep(backoff)
                continue

            # Sort by score desc, tie-break by to_string() to be deterministic
            filtered.sort(key=lambda x: (x[1], x[0].to_string()), reverse=True)

            # Take top N
            top_relays = [rid for (rid, _) in filtered[:TOP_N]]

            # Defensive: if top_relays empty (shouldn't be), backoff
            if not top_relays:
                backoff = min(2 ** attempt, 10)
                await trio.sleep(backoff)
                continue

            # Round-robin selection across the top_relays list
            # Ensure _last_relay_index cycles relative to top_relays length.
            if self._last_relay_index == -1:
                # First selection: pick best relay
                self._last_relay_index = 0
            else:
                # Next selections: cycle through top N
                self._last_relay_index = (self._last_relay_index + 1) % len(top_relays)
            chosen = top_relays[self._last_relay_index]

            # Ensure metrics access uses the actual relay object (or insert if missing)
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

            if status_code != StatusCode.OK:
                logger.warning(
                    "Reservation failed with relay %s: %s",
                    relay_peer_id,
                    status_msg,
                )
                return False

            # Store reservation info
            # TODO: Implement reservation storage and refresh mechanism
            return True

        except Exception as e:
            logger.error("Error making reservation: %s", str(e))
            return False

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
