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
from typing import TYPE_CHECKING, Any, Callable

from multiaddr import Multiaddr
import trio

from libp2p.abc import IMuxedConn, IMuxedStream, IRawConnection
from libp2p.connection_types import ConnectionType
from libp2p.peer.id import ID

from .config import WebRTCTransportConfig
from .constants import (
    ACCEPT_QUEUE_SIZE,
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

        # Trio token captured at construction time, used to safely route
        # aiortc callbacks (which run on the asyncio bridge thread) back
        # into the Trio thread via trio.from_thread.run_sync().  May be
        # None in unit tests that construct the connection outside a trio
        # task; in that case we call the mutations inline.
        try:
            self._trio_token: trio.lowlevel.TrioToken | None = (
                trio.lowlevel.current_trio_token()
            )
        except RuntimeError:
            self._trio_token = None

    # ------------------------------------------------------------------
    # IRawConnection interface
    # ------------------------------------------------------------------

    @property
    def is_initiator(self) -> bool:  # type: ignore[override]
        # IRawConnection declares is_initiator as a writable attribute while
        # IMuxedConn declares it as an abstract property; we satisfy the
        # property side because QUIC uses the same pattern.
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
            trio_token=self._trio_token,
        )

        # Create the data channel via the bridge
        if self._create_channel_cb is not None:
            try:
                await self._bridge.run_coro(self._create_channel_cb(channel_id, ""))
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
            raise WebRTCStreamError(
                "Connection closed while waiting for stream"
            ) from None

    # ------------------------------------------------------------------
    # Inbound data-channel handler (called by transport)
    # ------------------------------------------------------------------

    def on_datachannel(self, channel_id: int) -> WebRTCStream:
        """
        Register an inbound data channel as a new stream.

        Called by the transport layer when a remote peer creates a data channel.
        May be invoked from the asyncio bridge thread; any Trio-side
        enqueueing is routed through :meth:`_run_on_trio_thread`.

        :param channel_id: The data channel ID.
        :returns: The created :class:`WebRTCStream`.
        """
        # Pass our captured trio_token so the stream can route foreign-thread
        # callbacks back into trio even when constructed off-thread.
        stream = WebRTCStream(
            connection=self,
            channel_id=channel_id,
            is_initiator=False,
            trio_token=self._trio_token,
        )
        stream._send_callback = self._make_send_callback(channel_id)

        # Stream registry is guarded by threading.Lock so this is safe from
        # either thread.
        with self._streams_lock:
            self._streams[channel_id] = stream

        def _enqueue_stream() -> None:
            try:
                self._accept_send.send_nowait(stream)
            except (trio.WouldBlock, trio.ClosedResourceError):
                logger.warning(
                    "Accept queue full or closed, dropping inbound channel=%d",
                    channel_id,
                )

        self._run_on_trio_thread(_enqueue_stream)
        return stream

    def on_channel_message(self, channel_id: int, data: bytes) -> None:
        """
        Route a received data-channel message to the correct stream.

        Stream-level routing is done on whatever thread we're called from;
        the stream itself (:meth:`WebRTCStream.on_data`) handles the
        foreign-thread hand-off to Trio.
        """
        with self._streams_lock:
            stream = self._streams.get(channel_id)
        if stream is not None:
            stream.on_data(data)
        else:
            logger.debug("Message for unknown channel=%d, ignoring", channel_id)

    def on_channel_closed(self, channel_id: int) -> None:
        """Handle data-channel close event (safe from any thread)."""
        with self._streams_lock:
            stream = self._streams.pop(channel_id, None)
        if stream is not None:
            stream.on_channel_close()

    def _run_on_trio_thread(self, fn: Callable[[], None]) -> None:
        """
        Execute *fn* on the Trio thread.

        If we're already inside a Trio task, call directly.  Otherwise
        route through :func:`trio.from_thread.run_sync` using the captured
        token.  Falls back to a direct call if no token was captured
        (happens only in tests that construct the connection outside a
        trio run).
        """
        token = self._trio_token
        try:
            trio.lowlevel.current_task()
            in_trio = True
        except RuntimeError:
            in_trio = False

        if in_trio or token is None:
            fn()
        else:
            try:
                trio.from_thread.run_sync(fn, trio_token=token)
            except trio.RunFinishedError:
                logger.debug(
                    "WebRTCConnection: trio run finished, dropping "
                    "asyncio-side callback"
                )

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
                await self._bridge.run_coro(self._send_on_channel_cb(channel_id, data))

        return _send

    def remove_stream(self, channel_id: int) -> None:
        """Remove a stream from the registry (called on cleanup)."""
        with self._streams_lock:
            self._streams.pop(channel_id, None)
