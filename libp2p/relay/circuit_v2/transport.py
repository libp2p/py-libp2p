"""
Transport implementation for Circuit Relay v2.

This module implements the transport layer for Circuit Relay v2,
allowing peers to establish connections through relay nodes.
"""

from collections.abc import Awaitable, Callable
import logging

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
)
from .protocol_buffer import (
    StatusCode,
)

logger = logging.getLogger("libp2p.relay.circuit_v2.transport")


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
        )
        self._reservations: dict[ID, float] = {}  # relay_peer_id -> expiration timestamp
        self._reservation_refresh_tasks: dict[ID, trio.Nursery] = {}

    async def dial(
        self,
        maddr: multiaddr.Multiaddr,
    ) -> RawConnection:
        """
        Dial a peer using the multiaddr. Supports multi-hop relay addresses.
        """
        # Parse multi-hop relay addresses
        relay_hops = []
        base_addr = maddr
        # Extract relay hops from multiaddr
        while True:
            try:
                idx = base_addr.protocols().index("p2p-circuit")
                relay_addr = base_addr.decapsulate("p2p-circuit")
                relay_hops.append(relay_addr)
                base_addr = relay_addr
            except ValueError:
                break
        # If there are relay hops, dial through them recursively
        if relay_hops:
            return await self._dial_multi_hop(relay_hops, base_addr)
        # Otherwise, use the default single-hop logic
        return await self.dial_peer_info(PeerInfo(ID.from_base58(maddr.value_for_protocol("p2p")), [maddr]))

    async def _dial_multi_hop(self, relay_hops, target_addr) -> RawConnection:
        """
        Dial through multiple relays to reach the target address.
        """
        # For each relay, establish a connection and use it as the next hop
        current_stream = None
        for relay_addr in relay_hops:
            relay_peer_id = ID.from_base58(relay_addr.value_for_protocol("p2p"))
            current_stream = await self.host.new_stream(relay_peer_id, [PROTOCOL_ID])
            # Optionally, make a reservation at each hop
            await self._make_reservation(current_stream, relay_peer_id)
        # Final hop: connect to the target
        target_peer_id = ID.from_base58(target_addr.value_for_protocol("p2p"))
        hop_msg = HopMessage(
            type=HopMessage.CONNECT,
            peer=target_peer_id.to_bytes(),
        )
        await current_stream.write(hop_msg.SerializeToString())
        resp_bytes = await current_stream.read()
        resp = HopMessage()
        resp.ParseFromString(resp_bytes)
        status_code = getattr(resp.status, "code", StatusCode.OK)
        status_msg = getattr(resp.status, "message", "Unknown error")
        if status_code != StatusCode.OK:
            raise ConnectionError(f"Relay connection failed: {status_msg}")
        return RawConnection(stream=current_stream, initiator=True)

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

        Parameters
        ----------
        peer_info : PeerInfo
            The peer to connect to

        Returns
        -------
        Optional[ID]
            Selected relay peer ID, or None if no suitable relay found

        """
        # Try to find a relay
        attempts = 0
        while attempts < self.client_config.max_auto_relay_attempts:
            # Get a relay from the list of discovered relays
            relays = self.discovery.get_relays()
            if relays:
                # TODO: Implement more sophisticated relay selection
                # For now, just return the first available relay
                return relays[0]

            # Wait and try discovery
            await trio.sleep(1)
            attempts += 1

        return None

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
            # --- Begin new code ---
            expire = None
            if resp.HasField("reservation"):
                expire = getattr(resp.reservation, "expire", None)
            if expire:
                self._reservations[relay_peer_id] = expire
                # Schedule a refresh
                await self._schedule_reservation_refresh(relay_peer_id, expire)
            # --- End new code ---
            return True

        except Exception as e:
            logger.error("Error making reservation: %s", str(e))
            return False

    async def _schedule_reservation_refresh(self, relay_peer_id: ID, expire: float) -> None:
        """
        Schedule a reservation refresh before expiration.
        """
        # Cancel any existing refresh task
        if relay_peer_id in self._reservation_refresh_tasks:
            nursery = self._reservation_refresh_tasks.pop(relay_peer_id)
            nursery.cancel_scope.cancel()
        # Calculate refresh time
        now = trio.current_time()
        refresh_time = expire - (self.config.reservation_ttl * self.client_config.reservation_refresh_threshold)
        delay = max(0, refresh_time - now)
        async def refresh_task():
            await trio.sleep(delay)
            await self._refresh_reservation(relay_peer_id)
        nursery = trio.Nursery()
        self._reservation_refresh_tasks[relay_peer_id] = nursery
        nursery.start_soon(refresh_task)

    async def _refresh_reservation(self, relay_peer_id: ID) -> None:
        """
        Refresh a reservation with the relay.
        """
        try:
            stream = await self.host.new_stream(relay_peer_id, [PROTOCOL_ID])
            reserve_msg = HopMessage(
                type=HopMessage.RESERVE,
                peer=self.host.get_id().to_bytes(),
            )
            await stream.write(reserve_msg.SerializeToString())
            resp_bytes = await stream.read()
            resp = HopMessage()
            resp.ParseFromString(resp_bytes)
            status_code = getattr(resp.status, "code", StatusCode.OK)
            if status_code == StatusCode.OK:
                expire = getattr(resp.reservation, "expire", None)
                if expire:
                    self._reservations[relay_peer_id] = expire
                    await self._schedule_reservation_refresh(relay_peer_id, expire)
            await stream.close()
        except Exception as e:
            logger.error(f"Failed to refresh reservation with relay {relay_peer_id}: {e}")

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
        return CircuitV2Listener(self.host, self.protocol, self.config)


class CircuitV2Listener(Service, IListener):
    """Listener for incoming relay connections."""

    def __init__(
        self,
        host: IHost,
        protocol: CircuitV2Protocol,
        config: RelayConfig,
    ) -> None:
        """
        Initialize the Circuit v2 listener.

        Parameters
        ----------
        host : IHost
            The libp2p host this listener is running on
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
        # Implementation would go here

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
