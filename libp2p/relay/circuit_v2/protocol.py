"""
Circuit Relay v2 protocol implementation.

This module implements the Circuit Relay v2 protocol as specified in:
https://github.com/libp2p/specs/blob/master/relay/circuit-v2.md
"""

import logging
from typing import Optional, Dict, Tuple

import trio

from libp2p.abc import IHost, INetStream
from libp2p.custom_types import TProtocol
from libp2p.io.abc import ReadWriteCloser
from libp2p.peer.id import ID
from libp2p.tools.async_service import Service

from .pb import circuit_pb2 as proto
from .resources import RelayResourceManager, RelayLimits

logger = logging.getLogger("libp2p.relay.circuit_v2")

PROTOCOL_ID = TProtocol("/libp2p/circuit/relay/2.0.0")
STOP_PROTOCOL_ID = TProtocol("/libp2p/circuit/relay/2.0.0/stop")

# Default limits for relay resources
DEFAULT_RELAY_LIMITS = RelayLimits(
    duration=60 * 60,  # 1 hour
    data=1024 * 1024 * 1024,  # 1GB
    max_circuit_conns=8,
    max_reservations=4,
)


class CircuitV2Protocol(Service):
    """
    CircuitV2Protocol implements the Circuit Relay v2 protocol.

    This protocol allows peers to establish connections through relay nodes
    when direct connections are not possible (e.g., due to NAT).
    """

    def __init__(
        self,
        host: IHost,
        limits: Optional[RelayLimits] = None,
        allow_hop: bool = False,
    ) -> None:
        """
        Initialize the Circuit v2 protocol.

        Args:
            host: The libp2p host this protocol is running on
            limits: Resource limits for relay operations
            allow_hop: Whether to allow this node to act as a relay
        """
        super().__init__()
        self.host = host
        self.limits = limits or DEFAULT_RELAY_LIMITS
        self.allow_hop = allow_hop
        self.resource_manager = RelayResourceManager(self.limits)
        self._active_relays: Dict[ID, Tuple[INetStream, INetStream]] = {}

        # Register protocol handlers
        if self.allow_hop:
            self.host.set_stream_handler(PROTOCOL_ID, self._handle_hop_stream)
            self.host.set_stream_handler(STOP_PROTOCOL_ID, self._handle_stop_stream)

    async def run(self) -> None:
        """Run the protocol service."""
        try:
            await self.manager.wait_finished()
        finally:
            # Clean up any active relay connections
            for src_stream, dst_stream in self._active_relays.values():
                await src_stream.close()
                await dst_stream.close()
            self._active_relays.clear()

    async def _handle_hop_stream(self, stream: INetStream) -> None:
        """
        Handle incoming HOP streams.

        This handler processes relay requests from other peers.
        """
        try:
            # Read the incoming message
            msg_bytes = await stream.read()
            hop_msg = proto.HopMessage()
            hop_msg.ParseFromString(msg_bytes)

            # Process based on message type
            if hop_msg.type == proto.HopMessage.RESERVE:
                await self._handle_reserve(stream, hop_msg)
            elif hop_msg.type == proto.HopMessage.CONNECT:
                await self._handle_connect(stream, hop_msg)
            else:
                await self._send_status(
                    stream,
                    proto.Status.MALFORMED_MESSAGE,
                    "Invalid message type",
                )

        except Exception as e:
            logger.error("Error handling hop stream: %s", str(e))
            try:
                await self._send_status(
                    stream,
                    proto.Status.MALFORMED_MESSAGE,
                    str(e),
                )
            except Exception:
                pass
        finally:
            if stream.is_closed():
                await stream.close()

    async def _handle_stop_stream(self, stream: INetStream) -> None:
        """
        Handle incoming STOP streams.

        This handler processes incoming relay connections from the destination side.
        """
        try:
            # Read the incoming message
            msg_bytes = await stream.read()
            stop_msg = proto.StopMessage()
            stop_msg.ParseFromString(msg_bytes)

            if stop_msg.type != proto.StopMessage.CONNECT:
                await self._send_stop_status(
                    stream,
                    proto.Status.MALFORMED_MESSAGE,
                    "Invalid message type",
                )
                return

            # Get the source stream from active relays
            peer_id = ID(stop_msg.peer)
            if peer_id not in self._active_relays:
                await self._send_stop_status(
                    stream,
                    proto.Status.CONNECTION_FAILED,
                    "No pending relay connection",
                )
                return

            src_stream, _ = self._active_relays[peer_id]
            self._active_relays[peer_id] = (src_stream, stream)

            # Send success status to both sides
            await self._send_status(
                src_stream,
                proto.Status.OK,
                "Connection established",
            )
            await self._send_stop_status(
                stream,
                proto.Status.OK,
                "Connection established",
            )

            # Start relaying data
            async with trio.open_nursery() as nursery:
                nursery.start_soon(self._relay_data, src_stream, stream, peer_id)
                nursery.start_soon(self._relay_data, stream, src_stream, peer_id)

        except Exception as e:
            logger.error("Error handling stop stream: %s", str(e))
            try:
                await self._send_stop_status(
                    stream,
                    proto.Status.MALFORMED_MESSAGE,
                    str(e),
                )
            except Exception:
                pass
        finally:
            if stream.is_closed():
                await stream.close()

    async def _handle_reserve(self, stream: INetStream, msg: proto.HopMessage) -> None:
        """Handle a reservation request."""
        peer_id = ID(msg.peer)

        # Check if we can accept more reservations
        if not self.resource_manager.can_accept_reservation(peer_id):
            await self._send_status(
                stream,
                proto.Status.RESOURCE_LIMIT_EXCEEDED,
                "Reservation limit exceeded",
            )
            return

        # Create reservation
        reservation = self.resource_manager.create_reservation(peer_id)
        
        # Send response
        response = proto.HopMessage(
            type=proto.HopMessage.STATUS,
            status=proto.Status(code=proto.Status.OK),
            reservation=reservation.to_proto(),
            limit=proto.Limit(
                duration=self.limits.duration,
                data=self.limits.data,
            ),
        )
        await stream.write(response.SerializeToString())

    async def _handle_connect(self, stream: INetStream, msg: proto.HopMessage) -> None:
        """Handle a connect request."""
        peer_id = ID(msg.peer)

        # Verify reservation if provided
        if msg.HasField("reservation"):
            if not self.resource_manager.verify_reservation(peer_id, msg.reservation):
                await self._send_status(
                    stream,
                    proto.Status.PERMISSION_DENIED,
                    "Invalid reservation",
                )
                return

        # Check resource limits
        if not self.resource_manager.can_accept_connection(peer_id):
            await self._send_status(
                stream,
                proto.Status.RESOURCE_LIMIT_EXCEEDED,
                "Connection limit exceeded",
            )
            return

        try:
            # Store the source stream
            self._active_relays[peer_id] = (stream, None)

            # Try to connect to the destination
            dst_stream = await self.host.new_stream(peer_id, [STOP_PROTOCOL_ID])
            if not dst_stream:
                await self._send_status(
                    stream,
                    proto.Status.CONNECTION_FAILED,
                    "Could not connect to destination",
                )
                return

            # Send STOP CONNECT message
            stop_msg = proto.StopMessage(
                type=proto.StopMessage.CONNECT,
                peer=stream.get_remote_peer_id().to_bytes(),
            )
            await dst_stream.write(stop_msg.SerializeToString())

            # Wait for response from destination
            resp_bytes = await dst_stream.read()
            resp = proto.StopMessage()
            resp.ParseFromString(resp_bytes)

            if resp.status.code != proto.Status.OK:
                await self._send_status(
                    stream,
                    proto.Status.CONNECTION_FAILED,
                    resp.status.message,
                )
                return

            # Update active relays with destination stream
            self._active_relays[peer_id] = (stream, dst_stream)

            # Start relaying data
            async with trio.open_nursery() as nursery:
                nursery.start_soon(self._relay_data, stream, dst_stream, peer_id)
                nursery.start_soon(self._relay_data, dst_stream, stream, peer_id)

        except Exception as e:
            logger.error("Error establishing relay connection: %s", str(e))
            await self._send_status(
                stream,
                proto.Status.CONNECTION_FAILED,
                str(e),
            )
            if peer_id in self._active_relays:
                del self._active_relays[peer_id]

    async def _relay_data(
        self,
        src_stream: INetStream,
        dst_stream: INetStream,
        peer_id: ID,
    ) -> None:
        """
        Relay data between two streams.

        Args:
            src_stream: Source stream to read from
            dst_stream: Destination stream to write to
            peer_id: ID of the peer being relayed
        """
        try:
            while True:
                data = await src_stream.read()
                if not data:
                    break
                await dst_stream.write(data)

                # Update resource usage
                reservation = self.resource_manager._reservations.get(peer_id)
                if reservation:
                    reservation.data_used += len(data)
                    if reservation.data_used >= reservation.limits.data:
                        logger.warning("Data limit exceeded for peer %s", peer_id)
                        break

        except Exception as e:
            logger.error("Error relaying data: %s", str(e))
        finally:
            # Clean up streams and remove from active relays
            await src_stream.close()
            await dst_stream.close()
            if peer_id in self._active_relays:
                del self._active_relays[peer_id]

    async def _send_status(
        self,
        stream: ReadWriteCloser,
        code: proto.Status.Code,
        message: str,
    ) -> None:
        """Send a status message on the stream."""
        status_msg = proto.HopMessage(
            type=proto.HopMessage.STATUS,
            status=proto.Status(
                code=code,
                message=message,
            ),
        )
        await stream.write(status_msg.SerializeToString())

    async def _send_stop_status(
        self,
        stream: ReadWriteCloser,
        code: proto.Status.Code,
        message: str,
    ) -> None:
        """Send a status message on a STOP stream."""
        status_msg = proto.StopMessage(
            type=proto.StopMessage.STATUS,
            status=proto.Status(
                code=code,
                message=message,
            ),
        )
        await stream.write(status_msg.SerializeToString()) 