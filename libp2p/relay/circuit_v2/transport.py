"""
Transport implementation for Circuit Relay v2.

This module implements the transport layer for Circuit Relay v2,
allowing peers to establish connections through relay nodes.
"""

import logging
from typing import (
    Optional,
)

from libp2p.abc import (
    IHost,
    IListener,
    INetStream,
    ITransport,
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
from .pb import circuit_pb2 as proto
from .protocol import (
    PROTOCOL_ID,
    CircuitV2Protocol,
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
    ):
        """
        Initialize the Circuit v2 transport.

        Args:
            host: The libp2p host this transport is running on
            protocol: The Circuit v2 protocol instance
            config: Relay configuration
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

    async def dial(
        self,
        peer_info: PeerInfo,
        *,
        relay_peer_id: Optional[ID] = None,
    ) -> RawConnection:
        """
        Dial a peer through a relay.

        Args:
            peer_info: The peer to dial
            relay_peer_id: Optional specific relay peer to use

        Returns:
            RawConnection: The established connection

        Raises:
            ConnectionError: If the connection cannot be established
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
            hop_msg = proto.HopMessage(
                type=proto.HopMessage.CONNECT,
                peer=peer_info.peer_id.to_bytes(),
            )
            await relay_stream.write(hop_msg.SerializeToString())

            # Read response
            resp_bytes = await relay_stream.read()
            resp = proto.HopMessage()
            resp.ParseFromString(resp_bytes)

            if resp.status.code != proto.Status.OK:
                raise ConnectionError(f"Relay connection failed: {resp.status.message}")

            # Create raw connection from stream
            return RawConnection(
                stream=relay_stream,
                local_peer=self.host.get_id(),
                remote_peer=peer_info.peer_id,
            )

        except Exception as e:
            await relay_stream.close()
            raise ConnectionError(f"Failed to establish relay connection: {str(e)}")

    async def _select_relay(self, peer_info: PeerInfo) -> Optional[ID]:
        """
        Select an appropriate relay for the given peer.

        Args:
            peer_info: The peer to connect to

        Returns:
            Optional[ID]: Selected relay peer ID, or None if no suitable relay found
        """
        # Try to find a relay
        attempts = 0
        while attempts < self.client_config.max_auto_relay_attempts:
            relay_id = self.discovery.get_relay()
            if relay_id:
                # TODO: Implement more sophisticated relay selection
                # For now, just return the first available relay
                return relay_id

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

        Args:
            stream: Stream to the relay
            relay_peer_id: The relay's peer ID

        Returns:
            bool: True if reservation was successful
        """
        try:
            # Send reservation request
            reserve_msg = proto.HopMessage(
                type=proto.HopMessage.RESERVE,
                peer=self.host.get_id().to_bytes(),
            )
            await stream.write(reserve_msg.SerializeToString())

            # Read response
            resp_bytes = await stream.read()
            resp = proto.HopMessage()
            resp.ParseFromString(resp_bytes)

            if resp.status.code != proto.Status.OK:
                logger.warning(
                    "Reservation failed with relay %s: %s",
                    relay_peer_id,
                    resp.status.message,
                )
                return False

            # Store reservation info
            # TODO: Implement reservation storage and refresh mechanism
            return True

        except Exception as e:
            logger.error("Error making reservation: %s", str(e))
            return False

    def create_listener(self) -> IListener:
        """
        Create a listener for incoming relay connections.

        Returns:
            IListener: The created listener
        """
        return CircuitV2Listener(self.host, self.protocol, self.config)


class CircuitV2Listener(Service, IListener):
    """Listener for incoming relay connections."""

    def __init__(
        self,
        host: IHost,
        protocol: CircuitV2Protocol,
        config: RelayConfig,
    ):
        """
        Initialize the Circuit v2 listener.

        Args:
            host: The libp2p host this listener is running on
            protocol: The Circuit v2 protocol instance
            config: Relay configuration
        """
        super().__init__()
        self.host = host
        self.protocol = protocol
        self.config = config
        self.multiaddrs = []  # TODO: Add relay multiaddrs

    async def handle_incoming_connection(
        self,
        stream: INetStream,
        remote_peer_id: ID,
    ) -> RawConnection:
        """
        Handle an incoming relay connection.

        Args:
            stream: The incoming stream
            remote_peer_id: The remote peer's ID

        Returns:
            RawConnection: The established connection

        Raises:
            ConnectionError: If the connection cannot be established
        """
        if not self.config.enable_stop:
            raise ConnectionError("Stop role is not enabled")

        try:
            # Read STOP message
            msg_bytes = await stream.read()
            stop_msg = proto.StopMessage()
            stop_msg.ParseFromString(msg_bytes)

            if stop_msg.type != proto.StopMessage.CONNECT:
                raise ConnectionError("Invalid STOP message type")

            # Create raw connection
            return RawConnection(
                stream=stream,
                local_peer=self.host.get_id(),
                remote_peer=ID(stop_msg.peer),
            )

        except Exception as e:
            await stream.close()
            raise ConnectionError(f"Failed to handle incoming connection: {str(e)}")

    async def listen(self, multiaddr: str) -> None:
        """
        Start listening on the given multiaddr.

        Args:
            multiaddr: The multiaddr to listen on
        """
        # TODO: Implement proper multiaddr handling for relayed addresses
        self.multiaddrs.append(multiaddr)

    def get_addrs(self) -> list[str]:
        """Get the listening addresses."""
        return self.multiaddrs.copy()

    async def close(self) -> None:
        """Close the listener."""
        self.multiaddrs.clear()
        await self.manager.stop()
