"""
Discovery module for Circuit Relay v2.

This module handles discovering and tracking relay nodes in the network.
"""

from dataclasses import (
    dataclass,
)
import logging
import time
from typing import (
    Any,
    Protocol as TypingProtocol,
    cast,
    runtime_checkable,
)

import trio

from libp2p.abc import (
    IHost,
)
from libp2p.custom_types import (
    TProtocol,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.peer.peerstore import env_to_send_in_RPC
from libp2p.tools.async_service import (
    Service,
)

from .config import (
    DEFAULT_DISCOVERY_INTERVAL,
    DEFAULT_DISCOVERY_STREAM_TIMEOUT,
    DEFAULT_PEER_PROTOCOL_TIMEOUT,
)
from .pb.circuit_pb2 import (
    HopMessage,
)
from .protocol import (
    PROTOCOL_ID,
)
from .protocol_buffer import (
    StatusCode,
)
from .utils import (
    maybe_consume_signed_record,
)

logger = logging.getLogger("libp2p.relay.circuit_v2.discovery")

# Discovery constants
MAX_RELAYS_TO_TRACK = 10


# Extended interfaces for type checking
@runtime_checkable
class IHostWithMultiselect(TypingProtocol):
    """Extended host interface with multiselect attribute."""

    @property
    def multiselect(self) -> Any:
        """Get the multiselect component."""
        ...


@dataclass
class RelayInfo:
    """Information about a discovered relay."""

    peer_id: ID
    discovered_at: float
    last_seen: float
    has_reservation: bool = False
    reservation_expires_at: float | None = None
    reservation_data_limit: int | None = None


class RelayDiscovery(Service):
    """
    Discovery service for Circuit Relay v2 nodes.

    This service discovers and keeps track of available relay nodes, and optionally
    makes reservations with them.
    """

    def __init__(
        self,
        host: IHost,
        auto_reserve: bool = False,
        discovery_interval: int = DEFAULT_DISCOVERY_INTERVAL,
        max_relays: int = MAX_RELAYS_TO_TRACK,
        stream_timeout: int = DEFAULT_DISCOVERY_STREAM_TIMEOUT,
        peer_protocol_timeout: int = DEFAULT_PEER_PROTOCOL_TIMEOUT,
    ) -> None:
        """
        Initialize the discovery service.

        Parameters
        ----------
        host : IHost
            The libp2p host this discovery service is running on
        auto_reserve : bool
            Whether to automatically make reservations with discovered relays
        discovery_interval : int
            How often to run discovery, in seconds
        max_relays : int
            Maximum number of relays to track
        stream_timeout : int
            Timeout for stream operations during discovery, in seconds
        peer_protocol_timeout : int
            Timeout for checking peer protocol support, in seconds

        """
        super().__init__()
        self.host = host
        self.auto_reserve = auto_reserve
        self.discovery_interval = discovery_interval
        self.max_relays = max_relays
        self.stream_timeout = stream_timeout
        self.peer_protocol_timeout = peer_protocol_timeout
        self._discovered_relays: dict[ID, RelayInfo] = {}
        self._protocol_cache: dict[
            ID, set[str]
        ] = {}  # Cache protocol info to reduce queries
        self.event_started = trio.Event()
        self.is_running = False

    async def run(self, *, task_status: Any = trio.TASK_STATUS_IGNORED) -> None:
        """Run the discovery service."""
        try:
            self.is_running = True
            self.event_started.set()
            task_status.started()

            # Main discovery loop
            async with trio.open_nursery() as nursery:
                # Run initial discovery
                nursery.start_soon(self.discover_relays)

                # Set up periodic discovery
                while True:
                    await trio.sleep(self.discovery_interval)
                    if not self.manager.is_running:
                        break
                    nursery.start_soon(self.discover_relays)

                    # Cleanup expired relays and reservations
                    await self._cleanup_expired()

        finally:
            self.is_running = False

    async def discover_relays(self) -> None:
        r"""
        Discover relay nodes in the network.

        This method queries the network for peers that support the
        Circuit Relay v2 protocol.
        """
        logger.debug("Starting relay discovery")

        try:
            # Get connected peers
            connected_peers = self.host.get_connected_peers()
            logger.debug(
                "Checking %d connected peers for relay support", len(connected_peers)
            )

            # Check each peer if they support the relay protocol
            for peer_id in connected_peers:
                if peer_id == self.host.get_id():
                    continue  # Skip ourselves

                if peer_id in self._discovered_relays:
                    # Update last seen time for existing relay
                    self._discovered_relays[peer_id].last_seen = time.time()
                    continue

                # Don't wait too long for protocol info
                with trio.move_on_after(self.peer_protocol_timeout):
                    if await self._supports_relay_protocol(peer_id):
                        await self._add_relay(peer_id)

            # Limit number of relays we track
            if len(self._discovered_relays) > self.max_relays:
                # Sort by last seen time and keep only the most recent ones
                sorted_relays = sorted(
                    self._discovered_relays.items(),
                    key=lambda x: x[1].last_seen,
                    reverse=True,
                )
                to_remove = sorted_relays[self.max_relays :]
                for peer_id, _ in to_remove:
                    del self._discovered_relays[peer_id]

            logger.debug(
                "Discovery completed, tracking %d relays", len(self._discovered_relays)
            )

        except Exception as e:
            logger.error("Error during relay discovery: %s", str(e))

    async def _supports_relay_protocol(self, peer_id: ID) -> bool:
        """
        Check if a peer supports the relay protocol.

        Parameters
        ----------
        peer_id : ID
            The ID of the peer to check

        Returns
        -------
        bool
            True if the peer supports the relay protocol, False otherwise

        """
        # Check cache first
        if peer_id in self._protocol_cache:
            return PROTOCOL_ID in self._protocol_cache[peer_id]

        # Method 1: Try peerstore
        result = await self._check_via_peerstore(peer_id)
        if result is not None:
            return result

        # Method 2: Try direct stream connection
        result = await self._check_via_direct_connection(peer_id)
        if result is not None:
            return result

        # Method 3: Try protocols from mux
        result = await self._check_via_mux(peer_id)
        if result is not None:
            return result

        # Default: Cannot determine, assume false
        return False

    async def _check_via_peerstore(self, peer_id: ID) -> bool | None:
        """Check protocol support via peerstore."""
        try:
            peerstore = self.host.get_peerstore()
            proto_getter = peerstore.get_protocols

            if not callable(proto_getter):
                return None
            if peer_id not in peerstore.peer_ids():
                return None
            try:
                # Try to get protocols
                proto_result = proto_getter(peer_id)

                # Get protocols list
                protocols_list = []
                if hasattr(proto_result, "__await__"):
                    protocols_list = await cast(Any, proto_result)
                else:
                    protocols_list = proto_result

                # Check result
                if protocols_list is not None:
                    protocols = set(protocols_list)
                    self._protocol_cache[peer_id] = protocols
                    return PROTOCOL_ID in protocols

                return False
            except Exception as e:
                logger.debug("Error getting protocols: %s", str(e))
                return None
        except Exception as e:
            logger.debug("Error accessing peerstore: %s", str(e))
            return None

    async def _check_via_direct_connection(self, peer_id: ID) -> bool | None:
        """Check protocol support via direct connection."""
        try:
            with trio.fail_after(self.stream_timeout):
                stream = await self.host.new_stream(peer_id, [PROTOCOL_ID])
                if stream:
                    await stream.close()
                    self._protocol_cache[peer_id] = {PROTOCOL_ID}
                    return True
                return False
        except Exception as e:
            logger.debug(
                "Failed to open relay protocol stream to %s: %s", peer_id, str(e)
            )
            return None

    async def _check_via_mux(self, peer_id: ID) -> bool | None:
        """Check protocol support via mux protocols."""
        try:
            if not (hasattr(self.host, "get_mux") and self.host.get_mux() is not None):
                return None

            mux = self.host.get_mux()

            peer_protocols = set()
            # Get protocols from mux with proper type safety
            available_protocols = []
            if hasattr(mux, "get_protocols"):
                # Get protocols with proper typing
                mux_protocols = mux.get_protocols()
                if isinstance(mux_protocols, (list, tuple)):
                    available_protocols = [
                        p for p in mux.get_protocols() if p is not None
                    ]

            for protocol in available_protocols:
                try:
                    with trio.fail_after(2):  # Quick check
                        # Ensure we have a proper protocol object
                        # Use string representation since we can't use isinstance
                        is_tprotocol = str(type(protocol)) == str(type(TProtocol))
                        protocol_obj = (
                            protocol if is_tprotocol else TProtocol(str(protocol))
                        )
                        stream = await self.host.new_stream(peer_id, [protocol_obj])
                        if stream:
                            peer_protocols.add(str(protocol_obj))
                            await stream.close()
                except Exception:
                    pass  # Ignore errors when closing the stream

            self._protocol_cache[peer_id] = peer_protocols
            protocol_str = str(PROTOCOL_ID)
            for protocol in map(TProtocol, peer_protocols):
                if protocol == protocol_str:
                    return True
            return False
        except Exception as e:
            logger.debug("Error checking protocols via mux: %s", str(e))
            return None

    async def _add_relay(self, peer_id: ID) -> None:
        """
        Add a peer as a relay and optionally make a reservation.

        Parameters
        ----------
        peer_id : ID
            The ID of the peer to add as a relay

        """
        now = time.time()
        relay_info = RelayInfo(
            peer_id=peer_id,
            discovered_at=now,
            last_seen=now,
        )
        self._discovered_relays[peer_id] = relay_info
        logger.debug("Added relay %s to discovered relays", peer_id)

        # If auto-reserve is enabled, make a reservation with this relay
        if self.auto_reserve:
            await self.make_reservation(peer_id)

    async def make_reservation(self, peer_id: ID) -> bool:
        """
        Make a reservation with a relay.

        Parameters
        ----------
        peer_id : ID
            The ID of the relay to make a reservation with

        Returns
        -------
        bool
            True if reservation succeeded, False otherwise

        """
        if peer_id not in self._discovered_relays:
            logger.error("Cannot make reservation with unknown relay %s", peer_id)
            return False

        stream = None
        try:
            logger.debug("Making reservation with relay %s", peer_id)

            # Open a stream to the relay with timeout
            try:
                with trio.fail_after(self.stream_timeout):
                    stream = await self.host.new_stream(peer_id, [PROTOCOL_ID])
                    if not stream:
                        logger.error("Failed to open stream to relay %s", peer_id)
                        return False
            except trio.TooSlowError:
                logger.error("Timeout opening stream to relay %s", peer_id)
                return False

            try:
                # Prepare signed envelope
                envelope_bytes, _ = env_to_send_in_RPC(self.host)
                # Create and send reservation request
                request = HopMessage(
                    type=HopMessage.RESERVE,
                    peer=self.host.get_id().to_bytes(),
                    senderRecord=envelope_bytes,
                )

                with trio.fail_after(self.stream_timeout):
                    await stream.write(request.SerializeToString())

                    # Wait for response
                    response_bytes = await stream.read(1024)
                    if not response_bytes:
                        logger.error("No response received from relay %s", peer_id)
                        return False

                    # Parse response
                    response = HopMessage()
                    response.ParseFromString(response_bytes)

                    # Consume the source signed_peer_record if sent
                    if response.HasField("senderRecord"):
                        if not maybe_consume_signed_record(
                            response, self.host, peer_id
                        ):
                            logger.error(
                                "Received invalid senderRecord, dropping the stream"
                            )
                            await stream.close()
                            return False

                    # Check if reservation was successful
                    if response.type == HopMessage.STATUS and response.HasField(
                        "status"
                    ):
                        # Access status code directly from protobuf object
                        status_code = getattr(response.status, "code", StatusCode.OK)

                        if status_code == StatusCode.OK:
                            # Update relay info with reservation details
                            relay_info = self._discovered_relays[peer_id]
                            relay_info.has_reservation = True

                            if response.HasField("reservation") and response.HasField(
                                "limit"
                            ):
                                relay_info.reservation_expires_at = (
                                    response.reservation.expire
                                )
                                relay_info.reservation_data_limit = response.limit.data

                            logger.debug(
                                "Successfully made reservation with relay %s", peer_id
                            )
                            return True

                    # Reservation failed
                    error_message = "Unknown error"
                    if response.HasField("status"):
                        # Access message directly from protobuf object
                        error_message = getattr(response.status, "message", "")

                    logger.warning(
                        "Reservation request rejected by relay %s: %s",
                        peer_id,
                        error_message,
                    )
                    return False

            except trio.TooSlowError:
                logger.error(
                    "Timeout during reservation process with relay %s", peer_id
                )
                return False

        except Exception as e:
            logger.error("Error making reservation with relay %s: %s", peer_id, str(e))
            return False
        finally:
            # Always close the stream
            if stream:
                try:
                    await stream.close()
                except Exception:
                    pass  # Ignore errors when closing the stream

        return False

    async def _cleanup_expired(self) -> None:
        """Clean up expired relays and reservations."""
        now = time.time()
        to_remove = []

        for peer_id, relay_info in self._discovered_relays.items():
            # Check if relay hasn't been seen in a while (3x discovery interval)
            if now - relay_info.last_seen > self.discovery_interval * 3:
                to_remove.append(peer_id)
                continue

            # Check if reservation has expired
            if (
                relay_info.has_reservation
                and relay_info.reservation_expires_at
                and now > relay_info.reservation_expires_at
            ):
                relay_info.has_reservation = False
                relay_info.reservation_expires_at = None
                relay_info.reservation_data_limit = None

                # If auto-reserve is enabled, try to renew
                if self.auto_reserve:
                    await self.make_reservation(peer_id)

        # Remove expired relays
        for peer_id in to_remove:
            del self._discovered_relays[peer_id]
            if peer_id in self._protocol_cache:
                del self._protocol_cache[peer_id]

    def get_relays(self) -> list[ID]:
        """
        Get a list of discovered relay peer IDs.

        Returns
        -------
        list[ID]
            List of discovered relay peer IDs

        """
        return list(self._discovered_relays.keys())

    def get_relay_info(self, peer_id: ID) -> RelayInfo | None:
        """
        Get information about a specific relay.

        Parameters
        ----------
        peer_id : ID
            The ID of the relay to get information about

        Returns
        -------
        Optional[RelayInfo]
            Information about the relay, or None if not found

        """
        return self._discovered_relays.get(peer_id)

    def get_relay(self) -> ID | None:
        """
        Get a single relay peer ID for connection purposes.
        Prioritizes relays with active reservations.

        Returns
        -------
        Optional[ID]
            ID of a discovered relay, or None if no relays found

        """
        if not self._discovered_relays:
            return None

        # First try to find a relay with an active reservation
        for peer_id, relay_info in self._discovered_relays.items():
            if relay_info and relay_info.has_reservation:
                return peer_id

        return next(iter(self._discovered_relays.keys()), None)
