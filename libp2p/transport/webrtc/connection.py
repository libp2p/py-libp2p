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

        # Stream-specific channels
        self.send_channel: MemorySendChannel[bytes]
        self.receive_channel: MemoryReceiveChannel[bytes]
        self.send_channel, self.receive_channel = trio.open_memory_channel(100)

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

        # Message channels for raw data (when not using stream muxing)
        self.send_channel: MemorySendChannel[bytes]
        self.receive_channel: MemoryReceiveChannel[bytes]
        self.send_channel, self.receive_channel = trio.open_memory_channel(1000)

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

        # Store trio token for async callback handling
        try:
            self._trio_token: Any | None = trio.lowlevel.current_trio_token()
        except RuntimeError:
            # If we can't get the trio token, we'll use a fallback approach
            self._trio_token = None
            logger.warning("Could not get trio token, using fallback message handling")

        # Async bridge for WebRTC operations
        self._bridge = WebRTCAsyncBridge()

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
                self.send_channel.send_nowait(data)
                logger.debug(f"Delivered {len(data)} bytes to send_channel")
            except trio.WouldBlock:
                logger.warning("Message dropped - send_channel full!")
            except trio.ClosedResourceError:
                logger.debug("send_channel closed, message dropped")
            except Exception as e:
                logger.error(
                    f"Failed to deliver raw message to send_channel: {e}", exc_info=True
                )

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

        def on_message(message: Any) -> None:
            """Handle incoming message from WebRTC data channel"""
            if self._closed:
                logger.debug("Connection is closed, ignoring message")
                return

            try:
                # aiortc may pass the data directly as bytes,
                # or as an object with .data attribute
                if hasattr(message, "data"):
                    # Event-like object (similar to js-libp2p MessageEvent)
                    data = message.data
                    if isinstance(data, bytes):
                        pass  # Already bytes
                    elif hasattr(data, "tobytes"):
                        data = data.tobytes()
                    else:
                        data = bytes(data) if data else b""
                elif isinstance(message, bytes):
                    data = message
                else:
                    # Try to convert to bytes
                    try:
                        data = bytes(message)
                    except (TypeError, ValueError):
                        data = str(message).encode()

                if not data:
                    logger.debug("Received empty message, ignoring")
                    return

                # Deduplicate messages to prevent processing
                #  the same message multiple times
                # This can happen if aiortc calls the callback multiple times
                message_hash = hashlib.sha256(data).digest()
                with self._message_dedup_lock:
                    if message_hash in self._processed_messages:
                        logger.debug(f"Ignoring duplicate message ({len(data)} bytes)")
                        return
                    # Add to processed set
                    self._processed_messages.add(message_hash)
                    # Limit cache size to prevent memory growth
                    if len(self._processed_messages) > self._max_dedup_cache:
                        # Remove oldest entries (simple approach: clear and rebuild)
                        # In practice, this should rarely happen
                        self._processed_messages.clear()
                        self._processed_messages.add(message_hash)

                logger.debug(
                    "WebRTC on_message received (%d bytes): %.64r%s",
                    len(data),
                    data[:64],
                    "…" if len(data) > 64 else "",
                )

                # Try to parse as muxed stream data
                try:
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
                    # Not a muxed message, treat as raw data
                    pass

                # Deliver raw message - call directly since send_nowait is thread-safe
                try:
                    _deliver_raw_message(data)
                except Exception as deliver_err:
                    logger.error(
                        f"Failed to deliver raw message: {deliver_err}", exc_info=True
                    )

            except Exception as e:
                logger.critical(f"Error handling WebRTC message: {e}", exc_info=True)

        def on_open() -> None:
            """Handle channel open event"""
            logger.info(f"WebRTC channel opened to {self.peer_id}")

        def on_close() -> None:
            """Handle channel close event"""
            logger.info(f"WebRTC channel closed to {self.peer_id}")
            self._closed = True
            # Close trio channels safely
            try:
                self._schedule_async(self._close_trio_channels)
            except Exception as e:
                logger.warning(f"Error closing trio channels from WebRTC callback: {e}")

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
            self.data_channel.on("message", on_message)
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
                f"Handler complete. Channel state: {self.data_channel.readyState}"
            )
        except Exception as e:
            logger.error(f"Failed to register event handlers: {e}", exc_info=True)
            raise

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

        # Send through WebRTC data channel using async bridge
        try:
            message_data = json.dumps(message).encode("utf-8")
            async with self._bridge:
                await self._bridge.send_data(self.data_channel, message_data)
        except Exception as e:
            logger.error(f"Error sending stream {stream_id} data: {e}")
            raise

    async def _close_stream(self, stream_id: int) -> None:
        """Close a specific stream."""
        async with self._stream_lock:
            if stream_id in self._streams:
                del self._streams[stream_id]

        # Send close message to remote peer
        if not self._closed:
            try:
                message = {"stream_id": stream_id, "type": "close"}
                message_data = json.dumps(message).encode("utf-8")
                async with self._bridge:
                    await self._bridge.send_data(self.data_channel, message_data)
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
        if self._closed:
            logger.debug("Read called on closed connection")
            return b""

        async with self._read_lock:
            # If n is None, return all buffered data or wait
            if n is None:
                if not self._read_buffer:
                    try:
                        # Wait for data from channel
                        data = await self.receive_channel.receive()
                        self._read_buffer = data
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
                return result

            # For specific byte count requests, return UP TO n bytes from buffer
            # If buffer is empty, read from channel first
            if not self._read_buffer:
                try:
                    # Wait for data from channel
                    data = await self.receive_channel.receive()
                    self._read_buffer = data
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
            return result

    async def write(self, data: bytes) -> None:
        """Write data to the WebRTC data channel (raw mode)"""
        if self._closed:
            raise RuntimeError("Connection is closed")

        # Check data channel state before writing
        if self.data_channel.readyState != "open":
            logger.warning(
                f"Attempt write to data channel in: {self.data_channel.readyState}"
            )

        logger.info(
            "WebRTC raw write (%d bytes): %.64r%s (channel state: %s)",
            len(data),
            data[:64],
            "…" if len(data) > 64 else "",
            self.data_channel.readyState,
        )

        try:
            # Use async bridge for robust trio-asyncio integration
            async with self._bridge:
                await self._bridge.send_data(self.data_channel, data)
            logger.debug("WebRTC raw write completed successfully")
        except Exception as e:
            logger.error(f"Error writing to WebRTC connection: {e}", exc_info=True)
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

            self._closed = True

            async with self._stream_lock:
                streams_to_close = list(self._streams.values())
                self._streams.clear()

            for stream in streams_to_close:
                try:
                    await stream.close()
                except Exception as e:
                    logger.debug(f"Error closing stream (non-critical): {e}")

            try:
                async with self._bridge:
                    if hasattr(self.data_channel, "close"):
                        await self._bridge.close_data_channel(self.data_channel)

                    if hasattr(self.peer_connection, "close"):
                        await self._bridge.close_peer_connection(self.peer_connection)
            except Exception as e:
                # During cleanup, trio-asyncio context might not be available
                # This is non-critical, so we log and continue
                logger.debug(f"WebRTC resource cleanup failed (non-critical): {e}")

            await self._close_trio_channels()
            logger.info(f"WebRTC connection to {self.peer_id} closed")

        except Exception as e:
            logger.warning(f"Unexpected error during connection cleanup: {e}")
            self._closed = True
