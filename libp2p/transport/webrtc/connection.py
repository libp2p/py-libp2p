import json
import logging
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
        self._setup_channel_handlers()

        logger.info(f"WebRTC connection created to {peer_id}")

    @property
    def channel(self) -> RTCDataChannel:
        """Backward compatibility property."""
        return self.data_channel

    def _setup_channel_handlers(self) -> None:
        """Setup WebRTC channel event handlers with proper trio integration"""

        def on_message(message: Any) -> None:
            """Handle incoming message from WebRTC data channel"""
            if not self._closed:
                try:
                    # Convert message to bytes if needed
                    data = (
                        message if isinstance(message, bytes) else str(message).encode()
                    )

                    # Try to parse as muxed stream data
                    try:
                        parsed_msg = json.loads(data.decode("utf-8"))
                        if isinstance(parsed_msg, dict) and "stream_id" in parsed_msg:
                            self._handle_muxed_message(parsed_msg)
                            return
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        # Not a muxed message, treat as raw data
                        pass

                    # Use trio.from_thread to safely send from asyncio callback to trio
                    if self._trio_token:
                        try:
                            trio.from_thread.run_sync(
                                self.send_channel.send_nowait,
                                data,
                                trio_token=self._trio_token,
                            )
                        except trio.WouldBlock:
                            logger.warning("Message dropped: channel full")
                        except RuntimeError as e:
                            if "sniffio" in str(e).lower():
                                # Fallback for context detection issues
                                self._send_message_fallback(data)
                            else:
                                raise
                    else:
                        # Fallback when trio token is not available
                        self._send_message_fallback(data)

                except Exception as e:
                    logger.error(f"Error handling WebRTC message: {e}")

        def on_open() -> None:
            """Handle channel open event"""
            logger.info(f"WebRTC channel opened to {self.peer_id}")

        def on_close() -> None:
            """Handle channel close event"""
            logger.info(f"WebRTC channel closed to {self.peer_id}")
            self._closed = True
            # Close trio channels safely
            if self._trio_token:
                try:
                    _ = trio.from_thread.run(
                        self._close_trio_channels, trio_token=self._trio_token
                    )
                except Exception as e:
                    logger.warning(
                        f"Error closing trio channels from WebRTC callback: {e}"
                    )

        def on_error(error: Any) -> None:
            """Handle channel error event"""
            logger.error(f"WebRTC channel error to {self.peer_id}: {error}")
            self._closed = True

        # Set up WebRTC event handlers
        self.data_channel.on("message", on_message)
        self.data_channel.on("open", on_open)
        self.data_channel.on("close", on_close)
        self.data_channel.on("error", on_error)

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
                    if self._trio_token:
                        try:
                            trio.from_thread.run_sync(
                                stream.send_channel.send_nowait,
                                data,
                                trio_token=self._trio_token,
                            )
                        except trio.WouldBlock:
                            logger.warning(
                                f"Stream {stream_id} message dropped: channel full"
                            )
                        except Exception as e:
                            logger.error(f"Error sending to stream {stream_id}: {e}")
                    else:
                        # Fallback: store in a buffer or drop
                        logger.warning(
                            f"Cannot deliver msg to stream {stream_id}: no trio token"
                        )

            elif msg_type == "close":
                # Stream close message
                stream = self._streams.get(stream_id)
                if stream and self._trio_token:
                    try:
                        _ = trio.from_thread.run(
                            stream.close, trio_token=self._trio_token
                        )
                    except Exception as e:
                        logger.error(f"Error closing stream {stream_id}: {e}")

        except Exception as e:
            logger.error(f"Error handling muxed message: {e}")

    def _send_message_fallback(self, data: bytes) -> None:
        """Fallback message sending when trio context detection fails"""
        try:
            # Store message for later retrieval if channel is full
            self.send_channel.send_nowait(data)
        except trio.WouldBlock:
            logger.warning("Message dropped in fallback: channel full")
        except Exception as e:
            logger.error(f"Error in message fallback: {e}")

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
        """Read data from the WebRTC data channel (raw mode)"""
        if self._closed:
            return b""

        try:
            return await self.receive_channel.receive()
        except trio.ClosedResourceError:
            self._closed = True
            return b""
        except Exception as e:
            logger.error(f"Error reading from WebRTC connection: {e}")
            return b""

    async def write(self, data: bytes) -> None:
        """Write data to the WebRTC data channel (raw mode)"""
        if self._closed:
            raise RuntimeError("Connection is closed")

        try:
            # Use async bridge for robust trio-asyncio integration
            async with self._bridge:
                await self._bridge.send_data(self.data_channel, data)
        except Exception as e:
            logger.error(f"Error writing to WebRTC connection: {e}")
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
