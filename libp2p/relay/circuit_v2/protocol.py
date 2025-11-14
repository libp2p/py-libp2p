"""
Circuit Relay v2 protocol implementation.

This module implements the Circuit Relay v2 protocol as specified in:
https://github.com/libp2p/specs/blob/master/relay/circuit-v2.md
"""

import logging
import time
from typing import (
    Any,
    Protocol as TypingProtocol,
    cast,
    runtime_checkable,
)

import multiaddr
import trio

from libp2p.abc import (
    IHost,
    INetStream,
)
from libp2p.custom_types import (
    TProtocol,
)
from libp2p.io.abc import (
    ReadWriteCloser,
)
from libp2p.network.connection.raw_connection import (
    RawConnection,
)
from libp2p.peer.envelope import Envelope, unmarshal_envelope
from libp2p.peer.id import (
    ID,
)
from libp2p.peer.peerstore import env_to_send_in_RPC
from libp2p.stream_muxer.mplex.exceptions import (
    MplexStreamEOF,
    MplexStreamReset,
)
from libp2p.tools.async_service import (
    Service,
)
from libp2p.tools.constants import (
    MAX_READ_LEN,
)

from .config import (
    DEFAULT_MAX_CIRCUIT_BYTES,
    DEFAULT_MAX_CIRCUIT_CONNS,
    DEFAULT_MAX_CIRCUIT_DURATION,
    DEFAULT_MAX_RESERVATIONS,
    DEFAULT_PROTOCOL_CLOSE_TIMEOUT,
    DEFAULT_PROTOCOL_READ_TIMEOUT,
    DEFAULT_PROTOCOL_WRITE_TIMEOUT,
)
from .pb.circuit_pb2 import (
    HopMessage,
    Limit,
    Reservation,
    Status as PbStatus,
    StopMessage,
)
from .protocol_buffer import (
    StatusCode,
    create_status,
)
from .resources import (
    RelayLimits,
    RelayResourceManager,
)
from .utils import maybe_consume_signed_record

logger = logging.getLogger("libp2p.relay.circuit_v2")

PROTOCOL_ID = TProtocol("/libp2p/circuit/relay/2.0.0")
STOP_PROTOCOL_ID = TProtocol("/libp2p/circuit/relay/2.0.0/stop")


# Default limits for relay resources
DEFAULT_RELAY_LIMITS = RelayLimits(
    duration=DEFAULT_MAX_CIRCUIT_DURATION,
    data=DEFAULT_MAX_CIRCUIT_BYTES,
    max_circuit_conns=DEFAULT_MAX_CIRCUIT_CONNS,
    max_reservations=DEFAULT_MAX_RESERVATIONS,
)

# Stream operation timeouts
STREAM_READ_TIMEOUT = 15  # seconds
STREAM_WRITE_TIMEOUT = 15  # seconds
STREAM_CLOSE_TIMEOUT = 10  # seconds
MAX_READ_RETRIES = 3  # Balanced retries to handle temporary issues


# Extended interfaces for type checking
@runtime_checkable
class IHostWithStreamHandlers(TypingProtocol):
    """Extended host interface with stream handler methods."""

    def remove_stream_handler(self, protocol_id: TProtocol) -> None:
        """Remove a stream handler for a protocol."""
        ...


@runtime_checkable
class INetStreamWithExtras(TypingProtocol):
    """Extended net stream interface with additional methods."""

    def get_remote_peer_id(self) -> ID:
        """Get the remote peer ID."""
        ...

    def is_open(self) -> bool:
        """Check if the stream is open."""
        ...

    def is_closed(self) -> bool:
        """Check if the stream is closed."""
        ...


class CircuitV2Protocol(Service):
    """
    CircuitV2Protocol implements the Circuit Relay v2 protocol.

    This protocol allows peers to establish connections through relay nodes
    when direct connections are not possible (e.g., due to NAT).
    """

    def __init__(
        self,
        host: IHost,
        limits: RelayLimits | None = None,
        allow_hop: bool = False,
        read_timeout: int = DEFAULT_PROTOCOL_READ_TIMEOUT,
        write_timeout: int = DEFAULT_PROTOCOL_WRITE_TIMEOUT,
        close_timeout: int = DEFAULT_PROTOCOL_CLOSE_TIMEOUT,
    ) -> None:
        """
        Initialize a Circuit Relay v2 protocol instance.

        Parameters
        ----------
        host : IHost
            The libp2p host instance
        limits : RelayLimits | None
            Resource limits for the relay
        allow_hop : bool
            Whether to allow this node to act as a relay
        read_timeout : int
            Timeout for stream read operations, in seconds
        write_timeout : int
            Timeout for stream write operations, in seconds
        close_timeout : int
            Timeout for stream close operations, in seconds

        """
        self.host = host
        self.limits = limits or DEFAULT_RELAY_LIMITS
        self.allow_hop = allow_hop
        self.read_timeout = read_timeout
        self.write_timeout = write_timeout
        self.close_timeout = close_timeout
        self.resource_manager = RelayResourceManager(self.limits)
        self._active_relays: dict[ID, tuple[INetStream, INetStream | None]] = {}
        self.event_started = trio.Event()

    async def run(self, *, task_status: Any = trio.TASK_STATUS_IGNORED) -> None:
        """Run the protocol service."""
        try:
            # Register protocol handlers
            if self.allow_hop:
                logger.debug("Registering stream handlers for relay protocol")
                self.host.set_stream_handler(PROTOCOL_ID, self._handle_hop_stream)

            self.host.set_stream_handler(STOP_PROTOCOL_ID, self._handle_stop_stream)
            print("Stream handlers registered successfully")

            # Signal that we're ready
            self.event_started.set()
            task_status.started()
            logger.debug("Protocol service started")

            # Wait for service to be stopped
            await self.manager.wait_finished()
        finally:
            # Clean up any active relay connections
            for src_stream, dst_stream in self._active_relays.values():
                await self._close_stream(src_stream)
                await self._close_stream(dst_stream)
            self._active_relays.clear()

            # Unregister protocol handlers
            if self.allow_hop:
                try:
                    # Cast host to extended interface with remove_stream_handler
                    host_with_handlers = cast(IHostWithStreamHandlers, self.host)
                    host_with_handlers.remove_stream_handler(PROTOCOL_ID)
                    host_with_handlers.remove_stream_handler(STOP_PROTOCOL_ID)
                except Exception as e:
                    logger.error("Error unregistering stream handlers: %s", str(e))

    async def _close_stream(self, stream: INetStream | None) -> None:
        """Helper function to safely close a stream."""
        if stream is None:
            return

        try:
            with trio.fail_after(self.close_timeout):
                await stream.close()
        except Exception:
            try:
                await stream.reset()
            except Exception:
                pass

    async def _read_stream_with_retry(
        self,
        stream: INetStream,
        max_retries: int = MAX_READ_RETRIES,
    ) -> bytes | None:
        """
        Helper function to read from a stream with retries.

        Parameters
        ----------
        stream : INetStream
            The stream to read from
        max_retries : int
            Maximum number of read retries

        Returns
        -------
        Optional[bytes]
            The data read from the stream, or None if the stream is closed/reset

        Raises
        ------
        trio.TooSlowError
            If read timeout occurs after all retries
        Exception
            For other unexpected errors

        """
        retries = 0
        last_error: Any = None
        backoff_time = 0.2

        while retries < max_retries:
            try:
                logger.debug(
                    " Attempting to read from stream (attempt %d/%d)",
                    retries + 1,
                    max_retries,
                )
                data = await stream.read(MAX_READ_LEN)
                if not data:  # EOF
                    logger.debug("Stream EOF detected")
                    return None

                logger.debug("Successfully read %d bytes from stream", len(data))
                return data
            except trio.WouldBlock:
                # Just retry immediately if we would block
                retries += 1
                logger.debug(
                    "Stream would block (attempt %d/%d), retrying...",
                    retries,
                    max_retries,
                )
                await trio.sleep(backoff_time * retries)
                continue
            except (MplexStreamEOF, MplexStreamReset):
                # Stream closed/reset - no point retrying
                logger.debug("Stream closed/reset during read")
                return None
            except trio.TooSlowError as e:
                last_error = e
                logger.debug(
                    "Read timeout (attempt %d/%d), retrying...", retries, max_retries
                )
                if retries < max_retries:
                    await trio.sleep(backoff_time * retries)
                continue
            except Exception as e:
                logger.error("Unexpected error reading from stream: %s", str(e))
                last_error = e
                retries += 1
                if retries < max_retries:
                    await trio.sleep(backoff_time * retries)
                    continue
                raise

        if last_error:
            if isinstance(last_error, trio.TooSlowError):
                logger.error("Read timed out after %d retries", max_retries)
            raise last_error

        return None

    async def _handle_hop_stream(self, stream: INetStream) -> None:
        """
        Handle incoming HOP streams.

        This handler processes relay requests from other peers.
        """
        logger.debug("=== HOP STREAM HANDLER CALLED ===")
        remote_peer_id = stream.muxed_conn.peer_id
        remote_id = str(remote_peer_id)
        try:
            # Try to get peer ID first
            # try:
            #     # This block always fail
            #     stream_with_peer_id = cast(INetStreamWithExtras, stream)
            #     remote_peer_id = stream_with_peer_id.get_remote_peer_id()
            #     remote_id = str(remote_peer_id)
            # except Exception:
            #     # Fall back to address if peer ID not available
            #     remote_addr = stream.get_remote_address()
            #     remote_id = f"peer at {remote_addr}"
            #     if remote_addr else "unknown peer"

            logger.debug("Handling hop stream from %s", remote_id)

            # Handle multiple messages on the same stream with proper timeout handling
            while True:
                # First, handle the read timeout gracefully
                try:
                    with trio.fail_after(STREAM_READ_TIMEOUT * 2):
                        msg_bytes = await stream.read(1024)
                        if not msg_bytes:
                            logger.error(f"Empty read from stream from {remote_id}")

                            pb_status = PbStatus()
                            pb_status.code = PbStatus.Code.MALFORMED_MESSAGE
                            pb_status.message = "Empty message received"
                            signed_envelope, _ = env_to_send_in_RPC(self.host)
                            response = HopMessage(
                                type=HopMessage.STATUS,
                                status=pb_status,
                                senderRecord=signed_envelope,
                            )
                            await stream.write(response.SerializeToString())
                            await trio.sleep(
                                0.5
                            )  # Longer wait to ensure message is sent
                            continue
                except trio.TooSlowError:
                    logger.error(f"Timeout reading from hop stream from {remote_id}")
                    # Create a proto Status directly
                    pb_status = PbStatus()
                    pb_status.code = PbStatus.Code.CONNECTION_FAILED
                    pb_status.message = "Stream read timeout"
                    signed_envelope, _ = env_to_send_in_RPC(self.host)

                    response = HopMessage(
                        type=HopMessage.STATUS,
                        status=pb_status,
                        senderRecord=signed_envelope,
                    )
                    await stream.write(response.SerializeToString())
                    await trio.sleep(0.5)
                    break
                except Exception as e:
                    print(f"Error reading from hop stream from {remote_id}: {str(e)}")
                    pb_status = PbStatus()
                    pb_status.code = PbStatus.Code.MALFORMED_MESSAGE
                    pb_status.message = f"Read error: {str(e)}"
                    signed_envelope, _ = env_to_send_in_RPC(self.host)
                    response = HopMessage(
                        type=HopMessage.STATUS,
                        status=pb_status,
                        senderRecord=signed_envelope,
                    )
                    await stream.write(response.SerializeToString())
                    await trio.sleep(0.5)  # Longer wait to ensure the message is sent
                    break
                # Parse the message
                try:
                    hop_msg = HopMessage()
                    hop_msg.ParseFromString(msg_bytes)
                except Exception as e:
                    logger.error(f"Error parsing hop message from {remote_id}: {e}")

                    pb_status = PbStatus()
                    pb_status.code = PbStatus.Code.MALFORMED_MESSAGE
                    pb_status.message = f"Parse error: {str(e)}"
                    signed_envelope, _ = env_to_send_in_RPC(self.host)
                    response = HopMessage(
                        type=HopMessage.STATUS,
                        status=pb_status,
                        senderRecord=signed_envelope,
                    )
                    await stream.write(response.SerializeToString())
                    await trio.sleep(0.5)
                    continue
                if hop_msg.HasField("senderRecord"):
                    if not maybe_consume_signed_record(
                        hop_msg, self.host, remote_peer_id
                    ):
                        logger.error("Received invalid sender-records. Closing stream")
                        await self._close_stream(stream)
                        return

                # Process based on message type
                if hop_msg.type == HopMessage.RESERVE:
                    await self._handle_reserve(stream, hop_msg)
                elif hop_msg.type == HopMessage.CONNECT:
                    await self._handle_connect(stream, hop_msg)
                else:
                    logger.error(
                        f"Invalid message type {hop_msg.type} from {remote_id}"
                    )
                    peer_envelope = self.host.get_peerstore().get_peer_record(
                        self.host.get_id()
                    )
                    await self._send_status(
                        stream,
                        StatusCode.MALFORMED_MESSAGE,
                        f"Invalid message type: {hop_msg.type}",
                        peer_envelope,
                    )
                    continue
        except Exception as e:
            logger.error(
                f"Unexpected error handling hop stream from {remote_id}: {str(e)}"
            )
            try:
                # Send a nice error response using _send_status method
                peer_envelope = self.host.get_peerstore().get_peer_record(
                    self.host.get_id()
                )
                await self._send_status(
                    stream,
                    StatusCode.MALFORMED_MESSAGE,
                    f"Internal error: {str(e)}",
                    peer_envelope,
                )
            except Exception as e2:
                logger.error(f"Failed to send error response to {remote_id}: {str(e2)}")

    async def _handle_stop_stream(self, stream: INetStream) -> None:
        """
        Handle incoming STOP streams.

        This handler processes incoming relay connections from the destination side.
        """
        remote_peer_id = stream.muxed_conn.peer_id

        try:
            # Read the incoming message with timeout
            with trio.fail_after(STREAM_READ_TIMEOUT):
                msg_bytes = await stream.read(1024)
                stop_msg = StopMessage()
                stop_msg.ParseFromString(msg_bytes)

            if stop_msg.HasField("senderRecord"):
                if not maybe_consume_signed_record(stop_msg, self.host, remote_peer_id):
                    logger.error("Received invalid senderRecord. Closing stream")
                    await self._close_stream(stream)
                    return

            if stop_msg.type != StopMessage.CONNECT:
                # Use direct attribute access to create status object for error response
                relay_envelope_bytes, _ = env_to_send_in_RPC(self.host)
                relay_envelope = unmarshal_envelope(relay_envelope_bytes)
                await self._send_stop_status(
                    stream,
                    StatusCode.MALFORMED_MESSAGE,
                    "Invalid message type",
                    relay_envelope,
                )
                await self._close_stream(stream)
                return

            # Get the source peer's SPR to send to destination
            src_peer_id = ID(stop_msg.peer)
            src_peer_envelope = self.host.get_peerstore().get_peer_record(src_peer_id)

            # Get the destination peer's SPR to send to source
            dst_peer_id = stream.muxed_conn.peer_id
            _ = self.host.get_peerstore().get_peer_record(dst_peer_id)

            await self._send_stop_status(
                stream,
                StatusCode.OK,
                "Connection established",
                src_peer_envelope,
            )

            await self.handle_incoming_connection(stream, stop_msg.peer)
        except trio.TooSlowError:
            logger.error("Timeout reading from stop stream")
            relay_envelope_bytes, _ = env_to_send_in_RPC(self.host)
            relay_envelope = unmarshal_envelope(relay_envelope_bytes)
            await self._send_stop_status(
                stream,
                StatusCode.CONNECTION_FAILED,
                "Stream read timeout",
                relay_envelope,
            )
            await self._close_stream(stream)
        except Exception as e:
            logger.error("Error handling stop stream: %s", str(e))
            try:
                relay_envelope_bytes, _ = env_to_send_in_RPC(self.host)
                relay_envelope = unmarshal_envelope(relay_envelope_bytes)
                await self._send_stop_status(
                    stream,
                    StatusCode.MALFORMED_MESSAGE,
                    str(e),
                    relay_envelope,
                )
                await self._close_stream(stream)
            except Exception:
                pass

    async def handle_incoming_connection(
        self,
        stream: INetStream,
        remote_peer_id: bytes,
    ) -> None:
        """
        Handle an incoming relay connection.

        Parameters
        ----------
        stream : INetStream
            The incoming stream
        remote_peer_id : ID
            The remote peer's ID

        Raises
        ------
        ConnectionError
            If the connection cannot be established

        """
        try:
            # Create raw connection
            raw_conn = RawConnection(stream=stream, initiator=False)
            ma = multiaddr.Multiaddr(remote_peer_id)
            await self.host.upgrade_inbound_connection(raw_conn, ma)

        except Exception as e:
            await stream.close()
            raise ConnectionError(f"Failed to handle incoming connection: {str(e)}")

    async def _handle_reserve(self, stream: INetStream, msg: HopMessage) -> None:
        """Handle a reservation request."""
        peer_id = None
        try:
            peer_id = ID(msg.peer)
            logger.debug("Handling reservation request from peer %s", peer_id)
            signed_envelope_bytes, _ = env_to_send_in_RPC(self.host)
            signed_envelope = unmarshal_envelope(signed_envelope_bytes)

            # Check if we can accept more reservations
            if not self.resource_manager.can_accept_reservation(peer_id):
                logger.debug("Reservation limit exceeded for peer %s", peer_id)
                # Send status message with STATUS type
                status = create_status(
                    code=StatusCode.RESOURCE_LIMIT_EXCEEDED,
                    message="Reservation limit exceeded",
                )

                status_msg = HopMessage(
                    type=HopMessage.STATUS,
                    status=status,
                    senderRecord=signed_envelope.marshal_envelope(),
                )
                await stream.write(status_msg.SerializeToString())
                return

            # Accept reservation
            logger.debug("Accepting reservation from peer %s", peer_id)
            ttl = self.resource_manager.reserve(peer_id)

            # Send reservation success response
            with trio.fail_after(self.write_timeout):
                status = create_status(
                    code=StatusCode.OK, message="Reservation accepted"
                )

                response = HopMessage(
                    type=HopMessage.STATUS,
                    status=status,
                    reservation=Reservation(
                        expire=int(time.time() + ttl),
                        voucher=b"",  # We don't use vouchers yet
                        signature=b"",  # We don't use signatures yet
                    ),
                    limit=Limit(
                        duration=self.limits.duration,
                        data=self.limits.data,
                    ),
                    senderRecord=signed_envelope.marshal_envelope(),
                )

                # Log the response message details for debugging
                logger.debug(
                    f"Sending reservation response: type={response.type},",
                    "status={getattr(response.status, 'code', 'unknown')}, ttl={ttl}",
                )
                await stream.write(response.SerializeToString())
                # Add a small wait to ensure the message is fully sent
                await trio.sleep(0.1)

                logger.debug("Reservation response sent successfully")

        except Exception as e:
            logger.error("Error handling reservation request: %s", str(e))
            if cast(INetStreamWithExtras, stream).is_open():
                try:
                    # Send error response
                    await self._send_status(
                        stream,
                        StatusCode.CONNECTION_FAILED,
                        f"Failed to process reservation: {str(e)}",
                        signed_envelope,
                    )
                except Exception as send_err:
                    logger.error("Failed to send error response: %s", str(send_err))
        # finally:
        #     # Always close the stream when done with reservation
        #     try:
        #         with trio.fail_after(STREAM_CLOSE_TIMEOUT):
        #             await stream.close()
        #     except Exception as close_err:
        #         logger.error("Error closing stream: %s", str(close_err))

    async def _handle_connect(self, stream: INetStream, msg: HopMessage) -> None:
        """Handle a connect request."""
        peer_id = ID(msg.peer)
        source_addr = stream.muxed_conn.peer_id
        logger.debug("Handling CONNECT request for peer %s", peer_id)
        dst_stream: INetStream | None = None

        # Verify reservation if provided
        if msg.HasField("reservation"):
            if not self.resource_manager.verify_reservation(
                source_addr, msg.reservation
            ):
                relay_envelope_bytes, _ = env_to_send_in_RPC(self.host)
                relay_envelope = unmarshal_envelope(relay_envelope_bytes)
                await self._send_status(
                    stream,
                    StatusCode.PERMISSION_DENIED,
                    "Invalid reservation",
                    relay_envelope,
                )
                await stream.reset()
                return

        # Check resource limits
        if not self.resource_manager.can_accept_connection(peer_id=source_addr):
            relay_envelope_bytes, _ = env_to_send_in_RPC(self.host)
            relay_envelope = unmarshal_envelope(relay_envelope_bytes)
            await self._send_status(
                stream,
                StatusCode.RESOURCE_LIMIT_EXCEEDED,
                "Connection limit exceeded",
                relay_envelope,
            )
            await stream.reset()
            return

        try:
            # Store the source stream with properly typed None
            self._active_relays[source_addr] = (stream, None)
            logger.debug("Stored source stream for peer %s", source_addr)

            # Try to connect to the destination with timeout
            with trio.fail_after(STREAM_READ_TIMEOUT):
                logger.debug("Attempting to connect to destination %s", peer_id)
                dst_stream = await self.host.new_stream(peer_id, [STOP_PROTOCOL_ID])
                if not dst_stream:
                    raise ConnectionError("Could not connect to destination")
                logger.debug("Successfully connected to destination %s", peer_id)

                # Get remote peer's signed_peer_record and send to the destination peer
                # _ = cast(INetStreamWithExtras, stream).get_remote_peer_id()

                # Get relay's SPR to send in the STOP CONNECT message
                relay_envelope_bytes, _ = env_to_send_in_RPC(self.host)

                # Send STOP CONNECT message
                stop_msg = StopMessage(
                    type=StopMessage.CONNECT,
                    peer=source_addr.to_bytes(),
                    senderRecord=relay_envelope_bytes,
                )

                await dst_stream.write(stop_msg.SerializeToString())

                # Wait for response from destination
                resp_bytes = await dst_stream.read(1024)
                resp = StopMessage()
                resp.ParseFromString(resp_bytes)

                if resp.HasField("senderRecord"):
                    if not maybe_consume_signed_record(resp, self.host, peer_id):
                        logger.error(
                            "Received invalid signed-records from destination. "
                            "Closing stream"
                        )
                        await self._close_stream(stream)
                        return

                # Handle status attributes from the response
                if resp.HasField("status"):
                    # Get code and message attributes with defaults
                    status_code = getattr(resp.status, "code", StatusCode.OK)
                    # Get message with default
                    status_msg = getattr(resp.status, "message", "Unknown error")
                else:
                    status_code = StatusCode.OK
                    status_msg = "No status provided"

                if status_code != StatusCode.OK:
                    raise ConnectionError(
                        f"Destination rejected connection: {status_msg}"
                    )

            # Update active relays with destination stream
            self._active_relays[peer_id] = (stream, dst_stream)

            # Update reservation connection count
            reservation = self.resource_manager._reservations.get(peer_id)
            if reservation:
                reservation.active_connections += 1

            # Get destination peer's SPR to send to source
            signed_envelope = self.host.get_peerstore().get_peer_record(peer_id)

            # Send success status
            logger.debug("Sending OK status to source")
            await self._send_status(
                stream,
                StatusCode.OK,
                "Connection established",
                signed_envelope,
            )

            # Start relaying data
            async with trio.open_nursery() as nursery:
                nursery.start_soon(self._relay_data, stream, dst_stream, source_addr)
                nursery.start_soon(self._relay_data, dst_stream, stream, peer_id)

        except (trio.TooSlowError, ConnectionError) as e:
            logger.error("Error establishing relay connection: %s", str(e))
            logger.debug("Sending CONNECTION_FAILED status to source")
            relay_envelope_bytes, _ = env_to_send_in_RPC(self.host)
            relay_envelope = unmarshal_envelope(relay_envelope_bytes)
            await self._send_status(
                stream,
                StatusCode.CONNECTION_FAILED,
                str(e),
                relay_envelope,
            )
            if peer_id in self._active_relays:
                del self._active_relays[peer_id]
            # Clean up reservation connection count on failure
            reservation = self.resource_manager._reservations.get(peer_id)
            if reservation:
                reservation.active_connections -= 1
            await stream.reset()
            if dst_stream:
                await dst_stream.reset()
        except Exception as e:
            logger.error("Unexpected error in connect handler: %s", str(e))
            relay_envelope_bytes, _ = env_to_send_in_RPC(self.host)
            relay_envelope = unmarshal_envelope(relay_envelope_bytes)
            await self._send_status(
                stream,
                StatusCode.CONNECTION_FAILED,
                "Internal error",
                relay_envelope,
            )
            if peer_id in self._active_relays:
                del self._active_relays[peer_id]
            await stream.reset()
            if dst_stream:
                await dst_stream.reset()

    async def _relay_data(
        self,
        src_stream: INetStream,
        dst_stream: INetStream,
        peer_id: ID,
    ) -> None:
        """
        Relay data between two streams.

        Parameters
        ----------
        src_stream : INetStream
            Source stream to read from
        dst_stream : INetStream
            Destination stream to write to
        peer_id : ID
            ID of the peer being relayed

        """
        try:
            while True:
                # Read data with retries
                data = await self._read_stream_with_retry(src_stream)
                if not data:
                    logger.info("Source stream closed/reset")
                    break

                # Write data with timeout
                try:
                    with trio.fail_after(self.write_timeout):
                        await dst_stream.write(data)
                except trio.TooSlowError:
                    logger.error("Timeout writing to destination stream")
                    break
                except Exception as e:
                    logger.error("Error writing to destination stream: %s", str(e))
                    break

                # Update resource usage
                reservation = self.resource_manager._reservations.get(peer_id)
                if reservation:
                    reservation.data_used += len(data)
                    if reservation.data_used >= reservation.limits.data:
                        logger.warning("Data limit exceeded for peer %s", peer_id)
                        await self._send_status(
                            src_stream,
                            StatusCode.RESOURCE_LIMIT_EXCEEDED,
                            "Resource limit exceeded",
                        )
                        break

        except Exception as e:
            logger.error(f"Error relaying data: {e}")
        finally:
            # Clean up streams and remove from active relays
            # Only reset streams once to avoid double-reset issues
            if peer_id in self._active_relays:
                src_stream_cleanup, dst_stream_cleanup = self._active_relays[peer_id]
                await self._close_stream(src_stream_cleanup)
                await self._close_stream(dst_stream_cleanup)
                del self._active_relays[peer_id]

    async def _send_status(
        self,
        stream: ReadWriteCloser,
        code: int,
        message: str,
        envelope: Envelope | None = None,
    ) -> None:
        """Send a status message."""
        try:
            logger.debug("Sending status message with code %s: %s", code, message)
            with trio.fail_after(STREAM_WRITE_TIMEOUT):
                # Create a proto Status directly
                pb_status = PbStatus()
                pb_status.code = cast(
                    Any, int(code)
                )  # Cast to Any to avoid type errors
                pb_status.message = message

                # Send destination records to source in case of HOP status OK message
                status_msg = HopMessage(
                    type=HopMessage.STATUS,
                    status=pb_status,
                )
                if envelope is not None:
                    status_msg.senderRecord = envelope.marshal_envelope()

                msg_bytes = status_msg.SerializeToString()
                logger.debug("Status message serialized (%d bytes)", len(msg_bytes))

                await stream.write(msg_bytes)
                logger.debug("Status message sent successfully")
        except trio.TooSlowError:
            logger.error(
                "Timeout sending status message: code=%s, message=%s", code, message
            )
        except Exception as e:
            logger.error("Error sending status message: %s", str(e))

    async def _send_stop_status(
        self,
        stream: ReadWriteCloser,
        code: int,
        message: str,
        senderRecord: Envelope | None = None,
    ) -> None:
        """Send a status message on a STOP stream."""
        try:
            logger.debug("Sending stop status message with code %s: %s", code, message)
            with trio.fail_after(STREAM_WRITE_TIMEOUT):
                # Create a proto Status directly
                pb_status = PbStatus()
                pb_status.code = cast(
                    Any, int(code)
                )  # Cast to Any to avoid type errors
                pb_status.message = message

                status_msg = StopMessage(
                    type=StopMessage.STATUS,
                    status=pb_status,
                )
                if senderRecord is not None:
                    status_msg.senderRecord = senderRecord.marshal_envelope()

                await stream.write(status_msg.SerializeToString())
        except Exception as e:
            logger.error("Error sending stop status message: %s", str(e))
