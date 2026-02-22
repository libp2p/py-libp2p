import hashlib
import json
import logging
import threading
from typing import Any, cast

from aiortc import (
    RTCDataChannel,
    RTCPeerConnection,
)
from multiaddr import Multiaddr
import trio
from trio import (
    MemoryReceiveChannel,
    MemorySendChannel,
)

from libp2p.abc import IMuxedConn, INetStream, IRawConnection
from libp2p.custom_types import TProtocol
from libp2p.peer.id import ID

from .async_bridge import WebRTCAsyncBridge
from .constants import MUXER_READ_TIMEOUT

logger = logging.getLogger("libp2p.transport.webrtc.connection")


class WebRTCStream(INetStream):
    """
    A single stream over WebRTC data channel.
    This represents one multiplexed stream over the WebRTC connection.
    """

    def __init__(self, stream_id: int, connection: "WebRTCRawConnection"):
        self.stream_id = stream_id
        self.connection = connection
        self._closed = False
        self.protocol: TProtocol | None = None

        # Set muxed_conn as required by INetStream interface
        self.muxed_conn = cast(IMuxedConn, connection)

        channels: tuple[MemorySendChannel[bytes], MemoryReceiveChannel[bytes]] = (
            trio.open_memory_channel(1000)
        )
        self.send_channel: MemorySendChannel[bytes] = channels[0]
        self.receive_channel: MemoryReceiveChannel[bytes] = channels[1]

        logger.debug(f"Created WebRTC stream {stream_id}")

    def get_muxed_conn(self) -> IMuxedConn:
        """Get the underlying muxed connection."""
        return cast(IMuxedConn, self.connection)

    def set_protocol(self, protocol_id: TProtocol) -> None:
        """Set the protocol for this stream."""
        self.protocol = protocol_id
        logger.debug(f"Stream {self.stream_id} set protocol: {protocol_id}")

    def get_protocol(self) -> TProtocol | None:
        """Get the protocol for this stream."""
        return self.protocol

    def get_remote_address(self) -> tuple[str, int] | None:
        """
        Get the remote address for this stream.

        WebRTC connections don't expose IP:port addresses, so this returns None.
        """
        return None

    async def read(self, n: int | None = None) -> bytes:
        """Read data from the stream."""
        if self._closed:
            return b""

        try:
            return await self.receive_channel.receive()
        except trio.ClosedResourceError:
            self._closed = True
            return b""
        except Exception as e:
            logger.error(f"Error reading from WebRTC stream {self.stream_id}: {e}")
            return b""

    async def write(self, data: bytes) -> None:
        """Write data to the stream."""
        if self._closed:
            raise RuntimeError("Stream is closed")

        # Send data through the muxed connection
        await self.connection._send_stream_data(self.stream_id, data)

    async def close(self) -> None:
        """Close the stream."""
        if self._closed:
            return

        self._closed = True

        # Notify connection that stream is closed
        await self.connection._close_stream(self.stream_id)

        # Close local channels
        try:
            await self.send_channel.aclose()
        except Exception as e:
            logger.warning(f"Error closing stream {self.stream_id} send channel: {e}")

        try:
            await self.receive_channel.aclose()
        except Exception as e:
            logger.warning(
                f"Error closing stream {self.stream_id} receive channel: {e}"
            )

        logger.debug(f"Closed WebRTC stream {self.stream_id}")

    async def reset(self) -> None:
        """Reset the stream."""
        await self.close()


class WebRTCRawConnection(IRawConnection):
    """
    Wraps an RTCDataChannel to provide the IRawConnection interface
    required by py-libp2p with proper Trio async integration and stream muxing.
    """

    def __init__(
        self,
        peer_id: ID,
        peer_connection: RTCPeerConnection,
        data_channel: RTCDataChannel,
        is_initiator: bool = True,
        incoming_message_buffer: MemoryReceiveChannel[bytes] | None = None,
    ):
        self.peer_id = peer_id
        self.remote_peer_id = peer_id  # Alias for compatibility
        self.peer_connection = peer_connection
        self.data_channel = data_channel
        self._closed = False
        self.is_initiator = is_initiator

        self.local_multiaddr: Multiaddr | None = None
        self.remote_multiaddr: Multiaddr | None = None
        self.local_fingerprint: str | None = None
        self.remote_fingerprint: str | None = None

        # Stream muxing
        self._streams: dict[int, WebRTCStream] = {}
        self._next_stream_id: int = (
            1 if is_initiator else 2
        )  # Odd for initiator, even for responder
        self._stream_lock = trio.Lock()

        channels: tuple[MemorySendChannel[bytes], MemoryReceiveChannel[bytes]] = (
            trio.open_memory_channel(1000)
        )
        self.send_channel: MemorySendChannel[bytes] = channels[0]
        self.receive_channel: MemoryReceiveChannel[bytes] = channels[1]

        # CRITICAL FIX: The connection now OWNS its inbound pipe.
        inbound_channels: tuple[
            MemorySendChannel[bytes], MemoryReceiveChannel[bytes]
        ] = trio.open_memory_channel(1000)
        self._inbound_send_channel: MemorySendChannel[bytes] = inbound_channels[0]
        self._inbound_recv_channel: MemoryReceiveChannel[bytes] = inbound_channels[1]

        # If an early buffer was provided, we'll drain it
        self._incoming_message_buffer: MemoryReceiveChannel[bytes] | None = (
            incoming_message_buffer
        )

        # Read buffer for partial reads (required for read(n) to return exactly n bytes)
        self._read_buffer = b""
        self._read_lock = trio.Lock()

        # Track if handlers are already registered to prevent duplicate registration
        self._handlers_registered = False

        # Track recent message hashes to prevent duplicate processing
        # Use a simple set with a lock to prevent race conditions
        self._processed_messages: set[bytes] = set()
        self._message_dedup_lock = threading.Lock()
        # Keep only last 1000 message hashes to prevent memory growth
        self._max_dedup_cache = 1000

        # Track if handshake is in progress to prevent premature closure
        self._handshake_in_progress = False
        # Track handshake failure event for early abort
        self._handshake_failure_event: trio.Event | None = None

        # CRITICAL: Single ownership barrier - libp2p controls connection lifecycle
        # This event is set ONLY after:
        # 1. muxer negotiation finished
        # 2. Noise session established
        # 3. swarm.add_conn(conn) returned successfully
        # All WebRTC close paths must wait on this event, not check booleans.
        # Waiting removes race conditions that checking creates.
        self.libp2p_owner_ready = trio.Event()

        # Store trio token for async callback handling
        try:
            self._trio_token: Any | None = trio.lowlevel.current_trio_token()
        except RuntimeError:
            # If we can't get the trio token, we'll use a fallback approach
            self._trio_token = None
            logger.warning("Could not get trio token, using fallback message handling")

        # Async bridge for WebRTC operations
        self._bridge = WebRTCAsyncBridge()

        # Event to signal when buffer consumer is ready
        self._buffer_consumer_ready = trio.Event()

        # Start data pump immediately so handshake can run
        try:
            trio.lowlevel.spawn_system_task(self._data_pump_task)
            logger.info(f"🔵 Started data pump immediately for {peer_id}")
        except Exception as e:
            logger.error(f"Failed to start data pump: {e}", exc_info=True)
            # Still signal ready to avoid deadlock
            self._buffer_consumer_ready.set()

        # Setup channel event handlers with proper async bridging
        logger.info(
            f"Setting up channel handlers for WebRTC connection to {peer_id} "
            f"(channel state: {data_channel.readyState})"
        )
        self._setup_channel_handlers()

        # Verify handlers were registered
        logger.info(
            f"WebRTC connection created to {peer_id} "
            f"(channel state: {self.data_channel.readyState}, "
            f"closed: {self._closed})"
        )

    @property
    def channel(self) -> RTCDataChannel:
        """Backward compatibility property."""
        return self.data_channel

    def _schedule_sync(self, fn: Any, *args: Any) -> None:
        """
        Schedule a synchronous function to run in trio context.

        Since send_nowait on trio channels is thread-safe, we can call it directly
        from any context (trio or asyncio callback thread).
        """
        # send_nowait is thread-safe and can be called from any context
        # No need to bridge - just call directly
        try:
            fn(*args)
        except Exception as e:
            logger.error(f"Failed to execute sync function: {e}", exc_info=True)
            raise

    def _schedule_async(self, async_fn: Any, *args: Any) -> None:
        """Schedule an async function to run in trio context"""
        if self._trio_token:
            try:
                trio.from_thread.run(
                    async_fn,
                    *args,
                    trio_token=self._trio_token,
                )
                return
            except RuntimeError:
                # Fall back to best-effort scheduling if token unusable
                pass
        trio.lowlevel.spawn_system_task(async_fn, *args)

    def _setup_channel_handlers(self) -> None:
        """Setup WebRTC channel event handlers with proper trio integration"""
        # Prevent duplicate handler registration
        if self._handlers_registered:
            logger.warning(
                "Handlers already registered, skipping duplicate registration"
            )
            return

        def _deliver_raw_message(data: bytes) -> None:
            """Deliver incoming raw message to send_channel"""
            try:
                trio.lowlevel.current_task()
                is_in_trio = True
            except RuntimeError:
                is_in_trio = False
            try:
                if is_in_trio:
                    # We are in Trio (e.g. buffer consumer task),
                    # call directly
                    self.send_channel.send_nowait(data)
                elif self._trio_token:
                    # We are in asyncio thread, use bridge
                    # Use from_thread.run_sync for safety when in asyncio callback
                    try:
                        trio.from_thread.run_sync(
                            self.send_channel.send_nowait,
                            data,
                            trio_token=self._trio_token,
                        )
                    except Exception:
                        # Fallback: send_nowait should be thread-safe anyway
                        self.send_channel.send_nowait(data)
                else:
                    # No trio token - send_nowait should still work (it's thread-safe)
                    self.send_channel.send_nowait(data)
                logger.debug("Delivered %d bytes to send_channel", len(data))
            except trio.WouldBlock:
                logger.error(
                    "CHANNEL FULL - Message dropped (%d bytes)! "
                    "This blocks multistream handshake!",
                    len(data),
                )
                raise
            except trio.ClosedResourceError:
                logger.error("CHANNEL CLOSED - Cannot deliver message")
                raise
            except Exception as e:
                logger.error(
                    f"Failed to deliver raw message to send_channel: {e}",
                    exc_info=True,
                )
                raise

        def _deliver_stream_message(stream: "WebRTCStream", data: bytes) -> None:
            """Deliver incoming stream message to stream's send_channel"""
            try:
                stream.send_channel.send_nowait(data)
                logger.debug(
                    "Delivered stream %s message to send_channel (%d bytes)",
                    stream.stream_id,
                    len(data),
                )
            except trio.WouldBlock:
                logger.warning(
                    f"Stream {stream.stream_id} message dropped: send_channel full"
                )
            except trio.ClosedResourceError:
                logger.debug(f"Stream {stream.stream_id} send_channel closed")

        def _process_inbound_payload(data: bytes) -> None:
            """
            Centralized logic to process inbound data from ANY source
            (direct callback or buffer consumer).
            Handles metrics, deduplication, JSON-muxing check, and delivery.
            """
            if not data:
                return

            # 1. Metrics & First Byte Logging
            if not hasattr(self, "_bytes_received_count"):
                self._bytes_received_count = 0
                self._first_byte_received = False
            self._bytes_received_count += len(data)

            if not self._first_byte_received:
                self._first_byte_received = True
                logger.info(
                    f"🔵 FIRST BYTE PROCESSED for {self.peer_id} - "
                    f"{len(data)} bytes, first_16_bytes={data[:16].hex()}, "
                    f"total_bytes_received={self._bytes_received_count}"
                )

            # 2. Deduplication
            # This protects against both aiortc quirks AND race conditions between
            # early buffer and late handlers.
            message_hash = hashlib.sha256(data).digest()
            with self._message_dedup_lock:
                if message_hash in self._processed_messages:
                    logger.debug(f"Ignoring duplicate message ({len(data)} bytes)")
                    return
                self._processed_messages.add(message_hash)
                if len(self._processed_messages) > self._max_dedup_cache:
                    self._processed_messages.clear()
                    self._processed_messages.add(message_hash)

            # 3. Muxed Stream Logic (JSON Check)
            try:
                # Only attempt JSON parse if it looks like JSON to avoid overhead
                # Minimal check: starts with { and ends with }
                if data.startswith(b'{"stream_id":'):
                    parsed_msg = json.loads(data.decode("utf-8"))
                    if isinstance(parsed_msg, dict) and "stream_id" in parsed_msg:
                        logger.debug(
                            "Parsed as muxed stream message: stream_id=%s, type=%s",
                            parsed_msg.get("stream_id"),
                            parsed_msg.get("type"),
                        )
                        self._handle_muxed_message(parsed_msg)
                        return
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass

            # 4. Raw Delivery
            try:
                _deliver_raw_message(data)
            except Exception as deliver_err:
                logger.error(
                    f"Failed to deliver raw message: {deliver_err}", exc_info=True
                )

        def on_message(message: Any) -> None:
            """Handle incoming message from WebRTC data channel (Asyncio Callback)"""
            if self._closed:
                return

            try:
                # Extract bytes from message object
                data = b""
                if hasattr(message, "data"):
                    raw = message.data
                    if isinstance(raw, bytes):
                        data = raw
                    elif hasattr(raw, "tobytes"):
                        data = raw.tobytes()
                    else:
                        data = bytes(raw) if raw else b""
                elif isinstance(message, bytes):
                    data = message
                else:
                    try:
                        data = bytes(message)
                    except (TypeError, ValueError):
                        data = str(message).encode()

                if not data:
                    return

                # Log trace for debugging bridge
                logger.debug(f"🔵 [ASYNC BRIDGE] on_message received {len(data)} bytes")

                # Process using unified pipeline
                _process_inbound_payload(data)

            except Exception as e:
                logger.critical(f"Error handling WebRTC message: {e}", exc_info=True)

        def on_open() -> None:
            """Handle channel open event"""
            logger.info(f"WebRTC channel opened to {self.peer_id}")

        def on_close() -> None:
            """Handle channel close event"""
            logger.info(f"WebRTC channel closed to {self.peer_id}")
            # Get diagnostic states when channel closes
            conn_state = (
                getattr(self.peer_connection, "connectionState", None)
                if hasattr(self.peer_connection, "connectionState")
                else None
            )
            ice_state = (
                getattr(self.peer_connection, "iceConnectionState", None)
                if hasattr(self.peer_connection, "iceConnectionState")
                else None
            )
            ice_gathering = (
                getattr(self.peer_connection, "iceGatheringState", None)
                if hasattr(self.peer_connection, "iceGatheringState")
                else None
            )
            sctp_state = "N/A"
            try:
                if hasattr(self.peer_connection, "sctp") and self.peer_connection.sctp:
                    if hasattr(self.peer_connection.sctp, "transport"):
                        sctp_state = getattr(
                            self.peer_connection.sctp.transport, "state", "N/A"
                        )
            except Exception:
                pass
            buffered_amount = getattr(self.data_channel, "bufferedAmount", -1)

            # CRITICAL: Check ownership barrier - if libp2p owns the connection,
            # data channel close is just a transport event, not a shutdown signal
            # In asyncio callback context, we check if event is set (can't await here)
            if self.libp2p_owner_ready.is_set():
                logger.info(
                    f"Data channel closed but libp2p owns connection - "
                    f"ignoring close event (conn={conn_state}, ice={ice_state})"
                )
                return

            logger.warning(
                f"Data channel closed - states: "
                f"conn={conn_state}, ice={ice_state}, iceGather={ice_gathering}, "
                f"sctp={sctp_state}, buffered={buffered_amount}, "
                f"handshake_in_progress={self._handshake_in_progress}, "
                f"owner_ready={self.libp2p_owner_ready.is_set()}"
            )
            # Don't immediately mark as closed - allow handshake to complete
            # The connection might be closing during handshake, but we should
            # let the handshake error handling deal with it
            # Also, check if peer connection is still connected (ICE might be closed
            # but connection is still working)
            if not self._closed:
                # Check if handshake is in progress - abort early if channel closes
                if self._handshake_in_progress:
                    logger.error(
                        "Data channel closed during handshake - "
                        "aborting handshake early"
                    )
                    # Signal handshake failure for early abort
                    if self._handshake_failure_event is not None:
                        try:
                            self._handshake_failure_event.set()
                        except Exception as e:
                            logger.debug(f"Error setting handshake failure event: {e}")
                    self._closed = True
                    try:
                        self._schedule_async(self._close_trio_channels)
                    except Exception as e:
                        logger.warning(
                            f"Error closing trio channels from WebRTC callback: {e}"
                        )
                    return

                # Check if peer connection is still connected
                # ICE might be closed but connection is still working
                try:
                    if hasattr(self.peer_connection, "connectionState"):
                        conn_state = self.peer_connection.connectionState
                        if conn_state == "connected":
                            logger.info(
                                "Data channel closed but peer connection is still "
                                "connected - this is normal, connection is still usable"
                            )
                            return
                except Exception as e:
                    logger.debug(f"Could not check peer connection state: {e}")

                self._closed = True
                try:
                    self._schedule_async(self._close_trio_channels)
                except Exception as e:
                    logger.warning(
                        f"Error closing trio channels from WebRTC callback: {e}"
                    )

        def on_error(error: Any) -> None:
            """Handle channel error event"""
            logger.error(f"WebRTC channel error to {self.peer_id}: {error}")
            self._closed = True

        # Set up WebRTC event handlers
        logger.info(
            "Register event handlers for data channel ",
            f"(state: {self.data_channel.readyState}, "
            f"id: {getattr(self.data_channel, 'id', 'unknown')}, "
            f"label: {getattr(self.data_channel, 'label', 'unknown')})",
        )

        # Register handlers - aiortc uses .on() for event registration
        try:
            # FIX: We use ONE handler and ONLY one handler.
            # This prevents the double-delivery that was stalling Noise.
            self.data_channel.on("message", self.on_data_channel_message)
            logger.info(
                f"Registered single thread-safe message handler for {self.peer_id}"
            )

            # Standard lifecycle handlers
            self.data_channel.on("open", on_open)
            self.data_channel.on("close", on_close)
            self.data_channel.on("error", on_error)
            logger.info("WebRTC event handlers registered successfully")

            if self.data_channel.readyState == "open":
                logger.info("Data channel already open when handlers registered")
                try:
                    on_open()
                except Exception as e:
                    logger.warning(
                        f"Error triggering on_open for already-open channel: {e}"
                    )

            # Mark handlers as registered
            self._handlers_registered = True
            logger.info(
                f"Handler complete. Channel state: {self.data_channel.readyState}, "
                f"using_buffer: {self._incoming_message_buffer is not None}"
            )
        except Exception as e:
            logger.error(f"Failed to register event handlers: {e}", exc_info=True)
            raise

    def _start_buffer_consumer(self) -> None:
        """
        Mark that buffer consumer should be started.

        NOTE: The actual consumer task is started via start_buffer_consumer_async()
        which must be called from an async context. This method just marks that
        the consumer is needed.
        """
        if self._incoming_message_buffer is None:
            # No buffer - consumer not needed
            self._buffer_consumer_ready.set()
            return

        # Mark that consumer needs to be started
        # The actual start happens in start_buffer_consumer_async()
        logger.info(
            f"Buffer consumer marked for startup for {self.peer_id} "
            "(will be started in async context)"
        )

    async def _data_pump_task(self) -> None:
        """Permanent background task that pumps data into the libp2p stack."""
        logger.warning(f"🔵 Inbound Data Pump STARTED for {self.peer_id}")
        self._buffer_consumer_ready.set()
        messages_consumed = 0

        # 1. Drain the early buffer first (one-time migration)
        if self._incoming_message_buffer:
            try:
                drained = 0
                while True:
                    try:
                        data = self._incoming_message_buffer.receive_nowait()
                        self._inbound_send_channel.send_nowait(data)
                        drained += 1
                    except trio.WouldBlock:
                        break
                    except trio.EndOfChannel:
                        break
                if drained > 0:
                    logger.info("Drained %s msgs from early buffer", drained)
            except Exception as e:
                logger.debug(f"Error draining early buffer: {e}")

        # 2. Process live data from the internal channel
        try:
            async for data in self._inbound_recv_channel:
                if self._closed:
                    break
                messages_consumed += 1
                if messages_consumed == 1:
                    logger.warning(
                        f"🔵 FIRST MESSAGE CONSUMED from buffer for {self.peer_id}"
                    )

                # Deliver to send_channel for read() to consume.
                # Note: dedup/JSON-muxing is handled in on_data_channel_message
                # path; data pump just forwards raw bytes from the inbound channel.
                try:
                    self.send_channel.send_nowait(data)
                except trio.WouldBlock:
                    logger.warning(
                        "send_channel full in data pump for %s - "
                        "potential backpressure during muxer negotiation",
                        self.peer_id,
                    )
                except trio.ClosedResourceError:
                    logger.debug("send_channel closed in data pump")
                    break
                except Exception as proc_err:
                    logger.error(f"Error delivering buffered message: {proc_err}")
        except Exception as e:
            if not self._closed:
                logger.error(
                    f"Data pump crashed: {e} (consumed {messages_consumed} messages)",
                    exc_info=True,
                )
        finally:
            logger.info(
                f"🔵 Inbound Data Pump STOPPED for {self.peer_id} "
                f"(consumed {messages_consumed} messages total)"
            )

    def on_data_channel_message(self, message: Any) -> None:
        """Thread-safe entry point for aiortc callbacks."""
        try:
            # Extract bytes from message object
            if hasattr(message, "data"):
                data = message.data
                if isinstance(data, bytes):
                    pass
                elif hasattr(data, "tobytes"):
                    data = data.tobytes()
                else:
                    data = bytes(data) if data else b""
            elif isinstance(message, bytes):
                data = message
            else:
                try:
                    data = bytes(message)
                except (TypeError, ValueError):
                    data = str(message).encode()

            if not data:
                return

            # Transition data from Asyncio thread to Trio loop
            if self._trio_token:
                try:
                    trio.from_thread.run_sync(
                        self._inbound_send_channel.send_nowait,
                        data,
                        trio_token=self._trio_token,
                    )
                except Exception:
                    # Fallback if loop is stopping or token invalid
                    try:
                        self._inbound_send_channel.send_nowait(data)
                    except Exception:
                        pass
            else:
                # No token - try direct send (should be thread-safe)
                try:
                    self._inbound_send_channel.send_nowait(data)
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Error in on_data_channel_message: {e}", exc_info=True)

    async def start_buffer_consumer_async(self) -> None:
        """Legacy method - pump is already running, just wait for it to be ready."""
        # The pump is already started in __init__, just wait for it to signal ready
        if not self._buffer_consumer_ready.is_set():
            with trio.move_on_after(1.0) as timeout_scope:
                await self._buffer_consumer_ready.wait()
            if timeout_scope.cancelled_caught:
                logger.warning(f"Buffer consumer ready timeout for {self.peer_id}")

    def _handle_muxed_message(self, message: dict[str, Any]) -> None:
        """Handle muxed stream message"""
        try:
            stream_id_raw = message.get("stream_id")
            msg_type = message.get("type")

            # Ensure stream_id is an int
            if stream_id_raw is None:
                logger.warning("Received muxed message without stream_id")
                return

            try:
                stream_id = int(stream_id_raw)
            except (ValueError, TypeError):
                logger.warning(f"Invalid stream_id in muxed message: {stream_id_raw}")
                return

            if msg_type == "data":
                # Data message for a specific stream
                data = message.get("data", "").encode("utf-8")
                stream = self._streams.get(stream_id)
                if stream and not stream._closed:
                    # Deliver directly to stream's send_channel
                    try:
                        stream.send_channel.send_nowait(data)
                        logger.debug(
                            "WebRTC stream %s received (%d bytes)",
                            stream_id,
                            len(data),
                        )
                    except trio.WouldBlock:
                        logger.warning(
                            f"Stream {stream_id} message dropped: send_channel full"
                        )
                    except trio.ClosedResourceError:
                        logger.debug(f"Stream {stream_id} send_channel closed")

            elif msg_type == "close":
                # Stream close message
                stream = self._streams.get(stream_id)
                if stream:
                    try:
                        self._schedule_async(stream.close)
                    except Exception as e:
                        logger.error(f"Error closing stream {stream_id}: {e}")

        except Exception as e:
            logger.error(f"Error handling muxed message: {e}")

    async def _close_trio_channels(self) -> None:
        """Close trio channels safely"""
        try:
            await self.send_channel.aclose()
        except Exception as e:
            logger.warning(f"Error closing send channel: {e}")

        try:
            await self.receive_channel.aclose()
        except Exception as e:
            logger.warning(f"Error closing receive channel: {e}")

    async def open_stream(self) -> WebRTCStream:
        """Open a new stream over the WebRTC connection."""
        if self._closed:
            raise RuntimeError("Connection is closed")

        async with self._stream_lock:
            stream_id = self._next_stream_id
            self._next_stream_id += 2  # Maintain odd/even separation

            stream = WebRTCStream(stream_id, self)
            self._streams[stream_id] = stream

            logger.debug(f"Opened WebRTC stream {stream_id}")
            return stream

    async def accept_stream(self) -> WebRTCStream:
        """Accept an incoming stream over the WebRTC connection."""
        # For WebRTC, streams are created by the remote peer through data messages
        # This is a simplified implementation - in a full implementation,
        # we'd wait for stream open messages from the remote peer
        raise NotImplementedError("Stream acceptance not yet fully implemented")

    async def _send_stream_data(self, stream_id: int, data: bytes) -> None:
        """Send data for a specific stream."""
        if self._closed:
            raise RuntimeError("Connection is closed")

        # Create muxed message
        message = {
            "stream_id": stream_id,
            "type": "data",
            "data": data.decode("utf-8", errors="replace"),
        }
        logger.debug(
            "WebRTC sending stream %s payload (%d bytes)",
            stream_id,
            len(data),
        )

        # Check channel state before sending
        channel_state = getattr(self.data_channel, "readyState", "unknown")
        buffered_before = getattr(self.data_channel, "bufferedAmount", -1)
        conn_state = getattr(self.peer_connection, "connectionState", None)

        logger.debug(
            f"WebRTC sending stream {stream_id} - "
            f"channel_state={channel_state}, buffered={buffered_before}, "
            f"conn_state={conn_state}, "
            f"handshake_in_progress={self._handshake_in_progress}"
        )

        # Send through WebRTC data channel using async bridge
        try:
            message_data = json.dumps(message).encode("utf-8")
            async with self._bridge:
                await self._bridge.send_data(
                    self.data_channel, message_data, self.peer_connection
                )
        except Exception as e:
            channel_state_after = getattr(self.data_channel, "readyState", "unknown")
            logger.error(
                f"Error sending stream {stream_id} data: {e} - "
                f"channel_state_before={channel_state}, "
                f"channel_state_after={channel_state_after}, "
                f"handshake_in_progress={self._handshake_in_progress}",
                exc_info=True,
            )
            if channel_state_after == "closed" and self._handshake_in_progress:
                logger.error(
                    "Data channel closed during stream send while handshake in progress"
                )
            raise

    async def _close_stream(self, stream_id: int) -> None:
        """Close a specific stream."""
        async with self._stream_lock:
            if stream_id in self._streams:
                del self._streams[stream_id]

        # Send close message to remote peer
        if not self._closed:
            channel_state = getattr(self.data_channel, "readyState", "unknown")
            if channel_state == "closed":
                logger.debug(
                    f"Data channel already closed, skipping stream {stream_id} "
                    "close notification"
                )
                return

            try:
                message = {"stream_id": stream_id, "type": "close"}
                message_data = json.dumps(message).encode("utf-8")
                async with self._bridge:
                    await self._bridge.send_data(
                        self.data_channel, message_data, self.peer_connection
                    )
            except Exception as e:
                # During cleanup, trio-asyncio context might not be available
                # This is non-critical, so we log and continue
                logger.debug(f"Stream close notification failed (non-critical): {e}")

    async def read(self, n: int | None = None) -> bytes:
        """
        Read data from the WebRTC data channel (raw mode).

        Args:
            n: Maximum number of bytes to read. If None, read all available data.
               Returns up to n bytes .
               (not necessarily exactly n, matching TCP semantics).

        Returns:
            Data read from the channel (up to n bytes if n is specified)

        """
        if not hasattr(self, "_read_call_count"):
            self._read_call_count = 0
            self._first_read_called = False
        self._read_call_count += 1

        if not self._first_read_called:
            self._first_read_called = True
            logger.info(
                f"🔵 FIRST read() CALLED on WebRTCRawConnection for {self.peer_id} - "
                f"n={n}, owner_ready={self.libp2p_owner_ready.is_set()}, "
                f"channel_state={getattr(self.data_channel, 'readyState', 'unknown')}, "
                f"read_call_count={self._read_call_count}"
            )

        logger.debug(
            "read #%s n=%s state=%s",
            self._read_call_count,
            n,
            getattr(self.data_channel, "readyState", "unknown"),
        )

        if self._closed:
            logger.debug("Read called on closed connection")
            return b""

        # WebRTC quirk: data channel can report "closed"
        #  even when connection is "connected"
        if (
            hasattr(self.data_channel, "readyState")
            and self.data_channel.readyState == "closed"
        ):
            conn_state = getattr(self.peer_connection, "connectionState", None)
            if conn_state == "connected":
                logger.debug(
                    "Data channel reports closed but connection is connected - "
                    "attempting read anyway (WebRTC quirk)"
                )
            elif self._handshake_in_progress:
                logger.error(
                    "Read called on closed data channel during handshake - "
                    "handshake cannot complete. This indicates the data channel "
                    "closed prematurely."
                )
                raise RuntimeError(
                    "Data channel closed during handshake - "
                    "cannot read handshake messages"
                )
            else:
                # Handshake not in progress and connection not connected - return EOF
                return b""

        async with self._read_lock:
            logger.debug(
                "MUXER read peer=%s call#%s buf=%s n=%s",
                str(self.peer_id)[:12],
                getattr(self, "_read_call_count", 0),
                len(self._read_buffer),
                n,
            )
            if n is None:
                if not self._read_buffer:
                    try:
                        logger.debug("MUXER read wait (n=None) peer=%s", self.peer_id)
                        with trio.move_on_after(MUXER_READ_TIMEOUT) as read_scope:
                            data = await self.receive_channel.receive()
                        if read_scope.cancelled_caught:
                            ch_state = getattr(
                                self.data_channel, "readyState", "unknown"
                            )
                            conn_state = getattr(
                                self.peer_connection, "connectionState", "unknown"
                            )
                            logger.error(
                                "read() timed out after %.1fs for %s "
                                "(channel=%s, conn=%s) - "
                                "data pipeline may be stalled",
                                MUXER_READ_TIMEOUT,
                                self.peer_id,
                                ch_state,
                                conn_state,
                            )
                            raise trio.TooSlowError(
                                f"WebRTC read timed out after "
                                f"{MUXER_READ_TIMEOUT}s "
                                f"(channel={ch_state}, conn={conn_state})"
                            )
                        self._read_buffer = data
                    except trio.TooSlowError:
                        raise
                    except trio.ClosedResourceError:
                        self._closed = True
                        return b""
                    except Exception as e:
                        logger.error(
                            f"Error reading from WebRTC connection: {e}", exc_info=True
                        )
                        return b""

                # Return all buffered data
                result = self._read_buffer
                self._read_buffer = b""

                if result:
                    logger.debug(
                        "read returned %s bytes (n=None)",
                        len(result),
                    )

                return result

            # For specific byte count requests, return UP TO n bytes from buffer
            # If buffer is empty, read from channel first
            if not self._read_buffer:
                try:
                    logger.debug("MUXER read wait n=%s peer=%s", n, self.peer_id)
                    with trio.move_on_after(MUXER_READ_TIMEOUT) as read_scope:
                        data = await self.receive_channel.receive()
                    if read_scope.cancelled_caught:
                        ch_state = getattr(self.data_channel, "readyState", "unknown")
                        conn_state = getattr(
                            self.peer_connection, "connectionState", "unknown"
                        )
                        logger.error(
                            "read(n=%s) timed out after %.1fs for %s "
                            "(channel=%s, conn=%s)",
                            n,
                            MUXER_READ_TIMEOUT,
                            self.peer_id,
                            ch_state,
                            conn_state,
                        )
                        raise trio.TooSlowError(
                            f"WebRTC read timed out after {MUXER_READ_TIMEOUT}s"
                        )
                    self._read_buffer = data
                except trio.TooSlowError:
                    raise
                except trio.ClosedResourceError:
                    self._closed = True
                    return b""
                except Exception as e:
                    logger.error(
                        f"Error reading from WebRTC connection: {e}", exc_info=True
                    )
                    return b""

            # Return up to n bytes from buffer
            result = self._read_buffer[:n]
            self._read_buffer = self._read_buffer[n:]

            if result:
                logger.debug("read returned %s bytes", len(result))

            return result

    async def write(self, data: bytes) -> None:
        """Write data thread-safely to the SCTP queue via the Asyncio loop."""
        if self._closed:
            raise RuntimeError("Connection is closed")

        # FIX: Use WebRTCAsyncBridge.send_data()
        #  consistently for proper async context
        # This ensures thread safety, proper error handling,
        #  and channel state validation
        try:
            async with self._bridge:
                await self._bridge.send_data(
                    self.data_channel, data, self.peer_connection
                )
            logger.debug(
                f"🔵 write() successfully sent {len(data)} bytes via async bridge"
            )
        except Exception as e:
            logger.error(
                f"Failed to send WebRTC write via async bridge: {e}", exc_info=True
            )
            # Check if connection is still usable
            channel_state = getattr(self.data_channel, "readyState", "unknown")
            conn_state = getattr(self.peer_connection, "connectionState", None)
            logger.error(
                f"Write failed - channel_state={channel_state}, "
                f"conn_state={conn_state}, "
                f"handshake_in_progress={self._handshake_in_progress}"
            )
            # Only mark as closed if channel is actually closed
            if channel_state == "closed":
                self._closed = True
            raise

    def get_remote_address(self) -> tuple[str, int] | None:
        """Get remote address (not directly available in WebRTC)"""
        # WebRTC doesn't expose direct IP:port, return None
        return None

    async def close(self) -> None:
        """Close the WebRTC connection and clean up resources"""
        try:
            if self._closed:
                return

            # If handshake is in progress, log a warning but allow closure
            # (handshake error handling should deal with this)
            if self._handshake_in_progress:
                logger.warning(
                    "Connection close requested during handshake - "
                    "this may cause handshake to fail"
                )

            self._closed = True

            # Close message buffer if we're consuming from it
            # (The send side is closed when connect.py finishes)
            if self._incoming_message_buffer is not None:
                try:
                    await self._incoming_message_buffer.aclose()
                except Exception as e:
                    logger.debug(f"Error closing message buffer (non-critical): {e}")

            async with self._stream_lock:
                streams_to_close = list(self._streams.values())
                self._streams.clear()

            for stream in streams_to_close:
                try:
                    await stream.close()
                except Exception as e:
                    logger.debug(f"Error closing stream (non-critical): {e}")

            try:
                if self._bridge is not None:
                    try:
                        async with self._bridge:
                            if hasattr(self.data_channel, "close"):
                                await self._bridge.close_data_channel(self.data_channel)

                            if hasattr(self.peer_connection, "close"):
                                await self._bridge.close_peer_connection(
                                    self.peer_connection
                                )
                    except RuntimeError as e:
                        error_str = str(e).lower()
                        if (
                            "closed" in error_str
                            or "no running event loop" in error_str
                        ):
                            logger.debug(
                                "Event loop closed during cleanup (non-critical)"
                            )
                        else:
                            raise
                else:
                    logger.debug(
                        "Bridge is None during cleanup - skipping resource cleanup"
                    )
            except Exception as e:
                # During cleanup, trio-asyncio context might not be available
                # This is non-critical, so we log and continue
                logger.debug(f"WebRTC resource cleanup failed (non-critical): {e}")

            await self._close_trio_channels()
            logger.info(f"WebRTC connection to {self.peer_id} closed")

        except Exception as e:
            logger.warning(f"Unexpected error during connection cleanup: {e}")
            self._closed = True
