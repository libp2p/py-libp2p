"""
Transport implementation for Circuit Relay v2.

This module implements the transport layer for Circuit Relay v2,
allowing peers to establish connections through relay nodes.
"""

import logging

import multiaddr
import trio

from libp2p.abc import (
    IHost,
    IListener,
    INetConn,
    INetStream,
    ITransport,
)
from libp2p.custom_types import (
    THandler,
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
)
from .protocol import (
    PROTOCOL_ID,
    STREAM_READ_TIMEOUT,
    CircuitV2Protocol,
)
from .protocol_buffer import (
    StatusCode,
)
from .utils import (
    maybe_consume_signed_record,
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
            stream_timeout=config.timeouts.discovery_stream_timeout,
            peer_protocol_timeout=config.timeouts.peer_protocol_timeout,
        )

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

        dest_info = PeerInfo(ID.from_base58(dest_id_str), [maddr])
        logger.debug(f"Dialing destination peer ID: {dest_id_str} , \n {maddr}")
        # Use the internal dial_peer_info method
        if isinstance(relay_id_str, str):
            relay_peer_id = ID.from_base58(relay_id_str)
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
    ) -> RawConnection:
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
        # If no specific relay is provided, try to find one
        if relay_info is None:
            relay_peer_id = await self._select_relay(dest_info)
            if not relay_peer_id:
                raise ConnectionError("No suitable relay found")
            relay_info = self.host.get_peerstore().peer_info(relay_peer_id)
        await self.host.connect(relay_info)
        relay_peer_id = relay_info.peer_id
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
                    logger.error(
                        "Received an invalid senderRecord, dropping the stream"
                    )
                    await relay_stream.close()
                    raise ConnectionError("Invalid senderRecord")

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
                    logger.error(
                        "Received an invalid senderRecord, dropping the stream"
                    )
                    await stream.close()
                    return False

            # Access status attributes directly
            status_code = getattr(resp.status, "code", StatusCode.OK)
            status_msg = getattr(resp.status, "message", "Unknown error")

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

            # Store reservation info
            # TODO: Implement reservation storage and refresh mechanism
            return True

        except Exception as e:
            logger.error("Error making reservation: %s", str(e))
            return False

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
