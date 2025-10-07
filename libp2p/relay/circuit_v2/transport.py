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

    _last_relay_index: int

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

    async def dial(
        self,
        maddr: multiaddr.Multiaddr,
    ) -> RawConnection:
        """
        Dial a peer using the multiaddr.

        This method handles both direct and relayed dials. If the multiaddr
        is a /p2p-circuit address, it will be dialed through the specified
        relay. Otherwise, it will attempt to find an available relay.

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
        # Check if the multiaddr is a relayed address
        components = maddr.to_string().split("/p2p-circuit")
        if len(components) > 1 and components[0]:
            # This is a relayed address, of the form /p2p/relay_id/p2p-circuit/p2p/target_id
            relay_maddr = multiaddr.Multiaddr(components[0])
            target_maddr_str = components[1]
            if not target_maddr_str.startswith("/"):
                target_maddr_str = "/" + target_maddr_str
            target_maddr = multiaddr.Multiaddr(target_maddr_str)

            try:
                relay_peer_id_str = relay_maddr.value_for_protocol("p2p")
                target_peer_id_str = target_maddr.value_for_protocol("p2p")

                if not relay_peer_id_str or not target_peer_id_str:
                    raise ValueError("Missing peer ID")

                relay_peer_id = ID.from_base58(relay_peer_id_str)
                target_peer_id = ID.from_base58(target_peer_id_str)
                peer_info = PeerInfo(target_peer_id, [target_maddr])

                return await self.dial_peer_info(peer_info, relay_peer_id=relay_peer_id)

            except (ValueError, Exception) as e:
                raise ConnectionError(
                    f"Invalid p2p-circuit multiaddr: {maddr}, error: {e}"
                )

        # This is not a relayed address, so we need to find a relay
        try:
            peer_id_str = maddr.value_for_protocol("p2p")
            if not peer_id_str:
                raise ValueError("Multiaddr does not contain peer ID")

            peer_id = ID.from_base58(peer_id_str)
            peer_info = PeerInfo(peer_id, [maddr])

            # Use the internal dial_peer_info method to find a relay automatically
            return await self.dial_peer_info(peer_info)

        except (ValueError, Exception) as e:
            raise ConnectionError(f"Failed to dial non-relayed address {maddr}: {e}")

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

        # Ensure the relay is tracked by the discovery service for refresh.
        await self.discovery.add_relay(relay_peer_id)

        relay_info = self.discovery.get_relay_info(relay_peer_id)
        relay_stream = None
        try:
            # Get a stream to the relay
            relay_stream = await self.host.new_stream(relay_peer_id, [PROTOCOL_ID])
            if not relay_stream:
                raise ConnectionError(f"Could not open stream to relay {relay_peer_id}")

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

            # If successful, add the relay address to the peerstore for the remote peer.
            # This allows us to reconnect to the peer through the same relay in the future.
            relay_addr = multiaddr.Multiaddr(
                f"/p2p/{relay_peer_id.to_base58()}/p2p-circuit"
            )
            self.host.get_peerstore().add_addr(
                peer_info.peer_id, relay_addr, self.config.reservation_ttl
            )

            # Update stats for a successful connection.
            if relay_info:
                relay_info.successful_connects += 1

            # Create raw connection from stream
            return RawConnection(stream=relay_stream, initiator=True)

        except Exception as e:
            # Update stats for a failed connection.
            if relay_info:
                relay_info.failed_connects += 1
            if relay_stream:
                await relay_stream.close()
            raise ConnectionError(f"Failed to establish relay connection: {str(e)}")

    async def _select_relay(self, peer_info: PeerInfo) -> ID | None:
        """
        Select an appropriate relay for the given peer using a scoring model.

        The scoring model prioritizes relays with a higher success rate and
        lower latency.

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
            if not relays:
                # Wait and try discovery
                await trio.sleep(1)
                attempts += 1
                continue

            best_relay: ID | None = None
            max_score = -1.0

            for relay_id in relays:
                relay_info = self.discovery.get_relay_info(relay_id)
                if not relay_info:
                    continue

                # Calculate success rate (from 0.0 to 1.0)
                total_attempts = (
                    relay_info.successful_connects + relay_info.failed_connects
                )
                if total_attempts == 0:
                    # Prioritize new relays by giving them a default success rate of 100%.
                    success_rate = 1.0
                else:
                    success_rate = relay_info.successful_connects / total_attempts

                # Get latency from peerstore (in seconds)
                latency = self.host.get_peerstore().latency_EWMA(relay_id)
                if latency <= 0:
                    # Default to 1 second if no latency is available.
                    # This avoids division by zero and gives a neutral score.
                    latency = 1.0

                # Simple scoring model: success_rate / latency.
                # Lower latency and higher success rate result in a higher score.
                score = success_rate / latency

                if score > max_score:
                    max_score = score
                    best_relay = relay_id

            if best_relay:
                return best_relay

            # Wait and try discovery if no suitable relay was found
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

            # Store reservation info in the discovery service.
            relay_info = self.discovery.get_relay_info(relay_peer_id)
            if relay_info:
                relay_info.has_reservation = True
                if resp.HasField("reservation"):
                    relay_info.reservation_expires_at = resp.reservation.expire
                if resp.HasField("limit"):
                    relay_info.reservation_data_limit = resp.limit.data

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
            self.host, self.protocol, self.config, handler_function
        )


class CircuitV2Listener(Service, IListener):
    """Listener for incoming relay connections."""

    _handler_function: Callable[[ReadWriteCloser], Awaitable[None]]

    def __init__(
        self,
        host: IHost,
        protocol: CircuitV2Protocol,
        config: RelayConfig,
        handler_function: Callable[[ReadWriteCloser], Awaitable[None]],
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
        handler_function : Callable[[ReadWriteCloser], Awaitable[None]]
            The handler function for new connections

        """
        super().__init__()
        self.host = host
        self.protocol = protocol
        self.config = config
        self._handler_function = handler_function
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

        async def stream_handler(stream: INetStream) -> None:
            """Handle incoming streams."""
            try:
                # Use get_conn() to access the connection object and remote peer
                remote_peer_id = stream.get_conn().get_remote_peer()

                # Process the incoming connection
                raw_conn = await self.handle_incoming_connection(
                    stream, remote_peer_id
                )

                # Pass the connection to the handler
                await self._handler_function(raw_conn)

            except ConnectionError as e:
                logger.warning(
                    "Failed to handle incoming relayed connection: %s", str(e)
                )
                await stream.reset()
            except Exception as e:
                logger.error("Error handling incoming relayed connection: %s", str(e))
                await stream.reset()

        # Register the stream handler for the relay protocol
        self.host.set_stream_handler(PROTOCOL_ID, stream_handler)

        try:
            # Keep the listener running until cancelled
            await trio.sleep_forever()
        finally:
            # Clean up the stream handler when the service is stopped
            self.host.remove_stream_handler(PROTOCOL_ID)

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
