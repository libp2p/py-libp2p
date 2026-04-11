"""
WebRTC connection — dual ``IRawConnection`` + ``IMuxedConn`` interface.

Follows the same pattern as :class:`QUICConnection`: WebRTC provides native
stream multiplexing via data channels, so the connection implements both
the raw transport and the muxer interface.  The swarm skips the
TransportUpgrader for native-muxing transports.

Each outbound stream gets an even data-channel ID starting at 2.
Each inbound stream gets an odd data-channel ID starting at 1.
Channel 0 is reserved for the Noise handshake.

Spec: https://github.com/libp2p/specs/blob/master/webrtc/webrtc.md
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any

import trio
from multiaddr import Multiaddr

from libp2p.abc import IMuxedConn, IMuxedStream, IRawConnection
from libp2p.connection_types import ConnectionType
from libp2p.peer.id import ID

from .config import WebRTCTransportConfig
from .constants import (
    ACCEPT_QUEUE_SIZE,
    NOISE_HANDSHAKE_CHANNEL_ID,
    OUTBOUND_STREAM_START_ID,
)
from .exceptions import WebRTCConnectionError, WebRTCStreamError
from .stream import WebRTCStream

if TYPE_CHECKING:
    from ._asyncio_bridge import AsyncioBridge

logger = logging.getLogger(__name__)


class WebRTCConnection(IRawConnection, IMuxedConn):
    """
    A WebRTC peer connection providing native stream multiplexing.

    Wraps an aiortc ``RTCPeerConnection`` (via :class:`AsyncioBridge`)
    and maps each data channel to a :class:`WebRTCStream`.

    This class does NOT import or call aiortc directly.  All aiortc
    interaction happens through the bridge and the ``_send_on_channel`` /
    ``_create_channel`` / ``_close_pc`` callbacks set by the transport.
    This keeps the connection testable without aiortc installed.
    """

    def __init__(
        self,
        peer_id: ID,
        bridge: AsyncioBridge,
        is_initiator: bool,
        config: WebRTCTransportConfig | None = None,
        remote_addrs: list[Multiaddr] | None = None,
    ) -> None:
        # IMuxedConn required attribute
        self.peer_id = peer_id
        self.event_started = trio.Event()

        self._bridge = bridge
        self._is_init = is_initiator
        self._config = config or WebRTCTransportConfig()
        self._remote_addrs = remote_addrs or []

        # Connection state
        self._established = False
        self._closed = False
        self._started = False

        # Stream registry
        self._streams: dict[int, WebRTCStream] = {}
        self._streams_lock = threading.Lock()

        # Outbound channel ID counter: even IDs starting at 2
        self._next_outbound_id = OUTBOUND_STREAM_START_ID

        # Inbound stream accept queue
        self._accept_send: trio.MemorySendChannel[WebRTCStream]
        self._accept_recv: trio.MemoryReceiveChannel[WebRTCStream]
        self._accept_send, self._accept_recv = trio.open_memory_channel[WebRTCStream](
            ACCEPT_QUEUE_SIZE
        )

        # Callbacks set by the transport layer (avoids direct aiortc import)
        self._create_channel_cb: Any = None  # async (id, label) -> None
        self._send_on_channel_cb: Any = None  # async (channel_id, data) -> None
        self._close_pc_cb: Any = None  # async () -> None

    # ------------------------------------------------------------------
    # IRawConnection interface
    # ------------------------------------------------------------------

    @property
    def is_initiator(self) -> bool:
        return self._is_init

    def get_transport_addresses(self) -> list[Multiaddr]:
        return list(self._remote_addrs)

    def get_connection_type(self) -> ConnectionType:
        return ConnectionType.DIRECT

    def get_remote_address(self) -> tuple[str, int] | None:
        return None  # Populated after ICE negotiation completes

    async def read(self, n: int | None = None) -> bytes:
        # Raw reads are not used for native-muxing transports.
        # The swarm opens streams directly.
        raise WebRTCConnectionError(
            "WebRTC uses native multiplexing — read individual streams instead"
        )

    async def write(self, data: bytes) -> None:
        raise WebRTCConnectionError(
            "WebRTC uses native multiplexing — write to individual streams instead"
        )

    # ------------------------------------------------------------------
    # IMuxedConn interface
    # ------------------------------------------------------------------

    @property
    def is_established(self) -> bool:
        return self._established and not self._closed

    @property
    def is_closed(self) -> bool:
        return self._closed

    async def start(self) -> None:
        """Mark the connection as started.  Called after Noise handshake."""
        if self._started:
            return
        self._started = True
        self._established = True
        self.event_started.set()
        logger.debug("WebRTCConnection started (peer=%s)", self.peer_id)

    async def close(self) -> None:
        """Close the peer connection and all streams."""
        if self._closed:
            return
        self._closed = True
        self._established = False

        # Close all streams
        with self._streams_lock:
            streams = list(self._streams.values())
        for stream in streams:
            try:
                await stream.reset()
            except Exception:
                pass

        # Close the accept queue
        try:
            self._accept_send.close()
        except trio.ClosedResourceError:
            pass

        # Close the underlying peer connection
        if self._close_pc_cb is not None:
            try:
                await self._bridge.run_coro(self._close_pc_cb())
            except Exception:
                logger.debug("Error closing RTCPeerConnection", exc_info=True)

        logger.debug("WebRTCConnection closed (peer=%s)", self.peer_id)

    async def open_stream(self) -> IMuxedStream:
        """
        Open a new outbound stream (creates a WebRTC data channel).

        :returns: A :class:`WebRTCStream` ready for reading/writing.
        :raises WebRTCStreamError: If the connection is closed or stream
            limit is reached.
        """
        if self._closed:
            raise WebRTCStreamError("Connection is closed")

        channel_id = self._allocate_outbound_id()
        stream = WebRTCStream(
            connection=self,
            channel_id=channel_id,
            is_initiator=True,
        )

        # Create the data channel via the bridge
        if self._create_channel_cb is not None:
            try:
                await self._bridge.run_coro(
                    self._create_channel_cb(channel_id, "")
                )
            except Exception as e:
                raise WebRTCStreamError(
                    f"Failed to create data channel {channel_id}: {e}"
                ) from e

        # Wire up send callback
        stream._send_callback = self._make_send_callback(channel_id)

        # Register
        with self._streams_lock:
            self._streams[channel_id] = stream

        logger.debug(
            "Opened outbound stream channel=%d (peer=%s)",
            channel_id,
            self.peer_id,
        )
        return stream

    async def accept_stream(self) -> IMuxedStream:
        """
        Accept an inbound stream (waits for a remote data channel).

        :returns: A :class:`WebRTCStream`.
        :raises WebRTCStreamError: If the connection is closed.
        """
        if self._closed:
            raise WebRTCStreamError("Connection is closed")
        try:
            stream = await self._accept_recv.receive()
            return stream
        except trio.EndOfChannel:
            raise WebRTCStreamError("Connection closed while waiting for stream") from None

    # ------------------------------------------------------------------
    # Inbound data-channel handler (called by transport)
    # ------------------------------------------------------------------

    def on_datachannel(self, channel_id: int) -> WebRTCStream:
        """
        Register an inbound data channel as a new stream.

        Called by the transport layer when a remote peer creates a data channel.

        :param channel_id: The data channel ID.
        :returns: The created :class:`WebRTCStream`.
        """
        stream = WebRTCStream(
            connection=self,
            channel_id=channel_id,
            is_initiator=False,
        )
        stream._send_callback = self._make_send_callback(channel_id)

        with self._streams_lock:
            self._streams[channel_id] = stream

        # Enqueue for accept_stream()
        try:
            self._accept_send.send_nowait(stream)
        except (trio.WouldBlock, trio.ClosedResourceError):
            logger.warning(
                "Accept queue full or closed, dropping inbound channel=%d",
                channel_id,
            )

        return stream

    def on_channel_message(self, channel_id: int, data: bytes) -> None:
        """
        Route a received data-channel message to the correct stream.

        Called by the transport layer from the asyncio bridge.
        """
        with self._streams_lock:
            stream = self._streams.get(channel_id)
        if stream is not None:
            stream.on_data(data)
        else:
            logger.debug("Message for unknown channel=%d, ignoring", channel_id)

    def on_channel_closed(self, channel_id: int) -> None:
        """Handle data-channel close event."""
        with self._streams_lock:
            stream = self._streams.pop(channel_id, None)
        if stream is not None:
            stream.on_channel_close()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _allocate_outbound_id(self) -> int:
        """Allocate the next even data-channel ID for outbound streams."""
        with self._streams_lock:
            if len(self._streams) >= self._config.max_concurrent_streams:
                raise WebRTCStreamError(
                    f"Stream limit reached ({self._config.max_concurrent_streams})"
                )
            channel_id = self._next_outbound_id
            self._next_outbound_id += 2  # Even IDs only
        return channel_id

    def _make_send_callback(self, channel_id: int) -> Any:
        """Create a send callback for a specific data channel."""

        async def _send(data: bytes) -> None:
            if self._send_on_channel_cb is not None:
                await self._bridge.run_coro(
                    self._send_on_channel_cb(channel_id, data)
                )

        return _send

    def remove_stream(self, channel_id: int) -> None:
        """Remove a stream from the registry (called on cleanup)."""
        with self._streams_lock:
            self._streams.pop(channel_id, None)
