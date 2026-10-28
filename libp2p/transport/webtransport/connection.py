"""
WebTransport connection — QUIC + HTTP/3 WebTransport + native muxing.

Implements :class:`IRawConnection` and :class:`IMuxedConn` so the swarm skips
the security/muxer upgrader (``isinstance(..., IMuxedConn)``).
"""

from __future__ import annotations

import logging
import ssl
import time
from typing import Any

from aioquic.buffer import Buffer
from aioquic.h3.connection import H3_ALPN, FrameType, H3Connection
from aioquic.h3.events import (
    HeadersReceived,
    WebTransportStreamDataReceived,
)
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.connection import QuicConnection
from aioquic.quic.events import (
    ConnectionIdIssued,
    ConnectionIdRetired,
    ConnectionTerminated,
    HandshakeCompleted,
    QuicEvent,
    StreamReset,
)
from aioquic.quic.packet import QuicErrorCode, pull_quic_header
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from multiaddr import Multiaddr
import trio

from libp2p.abc import IMuxedConn, IMuxedStream, IRawConnection
from libp2p.connection_types import ConnectionType
from libp2p.peer.id import ID

from .certificate import multihash_from_der
from .config import WebTransportConfig
from .exceptions import WebTransportConnectionError, WebTransportStreamError
from .stream import WebTransportStream

logger = logging.getLogger(__name__)

# draft-ietf-webtrans-http3-06 (still sent by aioquic when enable_webtransport=True)
_SETTINGS_ENABLE_WEBTRANSPORT_DRAFT06 = 0x2B603742
# draft-ietf-webtrans-http3-15 — required by quic-go/webtransport-go ≥0.11
_SETTINGS_WT_ENABLED = 0x2C7CF000
_SETTINGS_WT_MAX_SESSIONS = 0x14E9CD29

# go-libp2p / webtransport-go send ``webtransport-h3``; accept legacy too.
_WT_PROTOCOLS = (b"webtransport", b"webtransport-h3")


def _now() -> float:
    return time.time()


class _Libp2pH3Connection(H3Connection):
    """
    aioquic H3Connection plus draft-15 WebTransport SETTINGS.

    go-libp2p v0.49 (webtransport-go v0.11) rejects peers that only advertise
    the draft-06 ENABLE_WEBTRANSPORT codepoint.
    """

    def _get_local_settings(self) -> dict[int, int]:
        settings = super()._get_local_settings()
        if self._enable_webtransport:
            settings[_SETTINGS_ENABLE_WEBTRANSPORT_DRAFT06] = 1
            settings[_SETTINGS_WT_ENABLED] = 1
            settings[_SETTINGS_WT_MAX_SESSIONS] = 1
        return settings


def _mark_local_webtransport_stream(
    h3: H3Connection, stream_id: int, session_id: int
) -> None:
    """
    Tell aioquic's H3 layer that *stream_id* carries WT payloads.

    ``create_webtransport_stream`` only sends the WT frame header; it does not
    set ``frame_type`` on the local ``H3Stream``. Without that, inbound bytes on
    the same bidi stream are mis-parsed as HTTP/3 frames.
    """
    with h3._get_or_create_stream(stream_id) as stream:  # noqa: SLF001
        stream.frame_type = FrameType.WEBTRANSPORT_STREAM
        stream.session_id = session_id


class WebTransportConnection(IRawConnection, IMuxedConn):
    """
    A WebTransport session over HTTP/3 providing native stream multiplexing.
    """

    def __init__(
        self,
        *,
        quic: QuicConnection,
        socket: trio.socket.SocketType,
        remote_addr: tuple[str, int],
        local_peer_id: ID,
        remote_peer_id: ID | None,
        is_initiator: bool,
        config: WebTransportConfig,
        maddr: Multiaddr | None = None,
        owns_socket: bool = True,
        nursery: trio.Nursery | None = None,
    ) -> None:
        self._quic = quic
        self._socket = socket
        self._remote_addr = remote_addr
        self._local_peer_id = local_peer_id
        self.peer_id = remote_peer_id or local_peer_id
        self._remote_peer_id = remote_peer_id
        self._is_initiator = is_initiator
        self._config = config
        self._maddr = maddr
        self._owns_socket = owns_socket
        self._nursery = nursery

        self.event_started = trio.Event()
        self._h3: H3Connection | None = None
        self._session_id: int | None = None
        self._noise_stream_id: int | None = None

        self._established = False
        self._closed = False
        self._started = False
        self._handshake_completed = trio.Event()
        self._connect_accepted = trio.Event()
        self._first_wt_stream = trio.Event()

        self._streams: dict[int, WebTransportStream] = {}
        self._stream_lock = trio.Lock()
        self._accept_send: trio.MemorySendChannel[WebTransportStream]
        self._accept_recv: trio.MemoryReceiveChannel[WebTransportStream]
        self._accept_send, self._accept_recv = trio.open_memory_channel[
            WebTransportStream
        ](self._config.accept_queue_size)

        self._peer_certificate: x509.Certificate | None = None
        self._used_cert_multihash: bytes | None = None
        self._transmit_lock = trio.Lock()
        self._pump_started = False

        # Host CIDs for listener demux (server side)
        self.host_cids: set[bytes] = set()
        if not is_initiator:
            # Original destination CID becomes our host CID after accept
            try:
                self.host_cids.add(bytes(quic.host_cid))
            except Exception:
                pass

    # ------------------------------------------------------------------
    # IRawConnection
    # ------------------------------------------------------------------

    @property
    def is_initiator(self) -> bool:  # type: ignore[override]
        return self._is_initiator

    def get_transport_addresses(self) -> list[Multiaddr]:
        return [self._maddr] if self._maddr is not None else []

    def get_connection_type(self) -> ConnectionType:
        return ConnectionType.DIRECT

    def get_remote_address(self) -> tuple[str, int] | None:
        return self._remote_addr

    async def read(self, n: int | None = None) -> bytes:
        raise WebTransportConnectionError(
            "WebTransport uses native multiplexing — read individual streams"
        )

    async def write(self, data: bytes) -> None:
        raise WebTransportConnectionError(
            "WebTransport uses native multiplexing — write to individual streams"
        )

    # ------------------------------------------------------------------
    # IMuxedConn
    # ------------------------------------------------------------------

    @property
    def is_established(self) -> bool:
        return self._established and not self._closed

    @property
    def is_closed(self) -> bool:
        return self._closed

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._established = True
        self.event_started.set()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._established = False
        try:
            self._quic.close(error_code=QuicErrorCode.NO_ERROR)
            await self.transmit()
        except Exception:
            pass
        try:
            self._accept_send.close()
        except trio.ClosedResourceError:
            pass
        if self._owns_socket:
            try:
                self._socket.close()
            except Exception:
                pass
        logger.debug("WebTransportConnection closed (peer=%s)", self.peer_id)

    async def open_stream(self) -> IMuxedStream:
        if self._closed or self._session_id is None or self._h3 is None:
            raise WebTransportStreamError("Connection not ready for streams")
        stream_id = self._h3.create_webtransport_stream(
            session_id=self._session_id, is_unidirectional=False
        )
        _mark_local_webtransport_stream(self._h3, stream_id, self._session_id)
        stream = WebTransportStream(self, stream_id, is_initiator=True)
        async with self._stream_lock:
            self._streams[stream_id] = stream
        await self.transmit()
        return stream

    async def accept_stream(self) -> IMuxedStream:
        if self._closed:
            raise WebTransportStreamError("Connection is closed")
        try:
            return await self._accept_recv.receive()
        except trio.EndOfChannel as e:
            raise WebTransportStreamError(
                "Connection closed while waiting for stream"
            ) from e

    # ------------------------------------------------------------------
    # QUIC / H3 pump
    # ------------------------------------------------------------------

    def attach_nursery(self, nursery: trio.Nursery) -> None:
        self._nursery = nursery

    async def start_pump(self) -> None:
        if self._pump_started or self._nursery is None:
            return
        self._pump_started = True
        self._nursery.start_soon(self._recv_loop)
        self._nursery.start_soon(self._timer_loop)

    async def transmit(self) -> None:
        async with self._transmit_lock:
            for data, addr in self._quic.datagrams_to_send(now=_now()):
                try:
                    await self._socket.sendto(data, addr)
                except Exception as e:
                    logger.debug("UDP sendto failed: %s", e)

    async def handle_datagram(self, data: bytes, addr: tuple[str, int]) -> None:
        self._remote_addr = addr
        self._quic.receive_datagram(data, addr, now=_now())
        await self._process_events()
        await self.transmit()

    async def _recv_loop(self) -> None:
        if not self._owns_socket:
            # Listener owns the socket and routes datagrams via handle_datagram.
            return
        while not self._closed:
            try:
                data, addr = await self._socket.recvfrom(65535)
            except (OSError, trio.ClosedResourceError):
                break
            try:
                await self.handle_datagram(data, addr)
            except Exception:
                logger.debug("Error handling datagram", exc_info=True)

    async def _timer_loop(self) -> None:
        while not self._closed:
            await trio.sleep(0.01)
            try:
                self._quic.handle_timer(now=_now())
                await self._process_events()
                await self.transmit()
            except Exception:
                if self._closed:
                    break
                logger.debug("Timer tick error", exc_info=True)

    async def _process_events(self) -> None:
        while True:
            event = self._quic.next_event()
            if event is None:
                break
            await self._handle_quic_event(event)

    async def _handle_quic_event(self, event: QuicEvent) -> None:
        if isinstance(event, HandshakeCompleted):
            self._extract_peer_certificate()
            if self._h3 is None:
                self._h3 = _Libp2pH3Connection(self._quic, enable_webtransport=True)
            self._handshake_completed.set()
        elif isinstance(event, ConnectionIdIssued):
            self.host_cids.add(bytes(event.connection_id))
        elif isinstance(event, ConnectionIdRetired):
            self.host_cids.discard(bytes(event.connection_id))
        elif isinstance(event, ConnectionTerminated):
            self._closed = True
            self._established = False
            try:
                self._accept_send.close()
            except trio.ClosedResourceError:
                pass
        elif isinstance(event, StreamReset):
            stream = self._streams.get(event.stream_id)
            if stream is not None:
                stream.on_data(b"", stream_ended=True)

        if self._h3 is not None:
            for h3_event in self._h3.handle_event(event):
                await self._handle_h3_event(h3_event)

    async def _handle_h3_event(self, event: Any) -> None:
        if isinstance(event, HeadersReceived):
            headers = {k: v for k, v in event.headers}
            status = headers.get(b":status")
            method = headers.get(b":method")
            protocol = headers.get(b":protocol")
            path = headers.get(b":path", b"").decode("utf-8", errors="replace")

            if self._is_initiator and status == b"200":
                self._session_id = event.stream_id
                self._connect_accepted.set()
            elif (
                not self._is_initiator
                and method == b"CONNECT"
                and protocol in _WT_PROTOCOLS
            ):
                assert self._h3 is not None
                if not path.startswith("/.well-known/libp2p-webtransport"):
                    self._h3.send_headers(
                        stream_id=event.stream_id,
                        headers=[(b":status", b"404")],
                        end_stream=True,
                    )
                    return
                self._h3.send_headers(
                    stream_id=event.stream_id,
                    headers=[
                        (b":status", b"200"),
                        (b"sec-webtransport-http3-draft", b"draft02"),
                    ],
                )
                self._session_id = event.stream_id
                self._connect_accepted.set()

        elif isinstance(event, WebTransportStreamDataReceived):
            await self._on_wt_stream_data(
                event.stream_id, event.data, event.stream_ended, event.session_id
            )

    async def _on_wt_stream_data(
        self,
        stream_id: int,
        data: bytes,
        stream_ended: bool,
        session_id: int,
    ) -> None:
        if self._session_id is None:
            self._session_id = session_id
        stream = self._streams.get(stream_id)
        if stream is None:
            # First client-opened stream is reserved for Noise on both sides.
            is_noise = self._noise_stream_id is None
            stream = WebTransportStream(self, stream_id, is_initiator=False)
            async with self._stream_lock:
                self._streams[stream_id] = stream
            if is_noise:
                self._noise_stream_id = stream_id
            else:
                try:
                    self._accept_send.send_nowait(stream)
                except (trio.WouldBlock, trio.ClosedResourceError):
                    logger.warning("Accept queue full, dropping stream %d", stream_id)

        if data or stream_ended:
            stream.on_data(data, stream_ended=stream_ended)

        # Signal after buffering data so the waiter cannot race an empty read.
        if self._noise_stream_id == stream_id and not self._first_wt_stream.is_set():
            self._first_wt_stream.set()

    def _extract_peer_certificate(self) -> None:
        try:
            tls_ctx = self._quic.tls
            peer_cert = getattr(tls_ctx, "_peer_certificate", None)
            if peer_cert is not None:
                self._peer_certificate = peer_cert
                der = peer_cert.public_bytes(serialization.Encoding.DER)
                self._used_cert_multihash = multihash_from_der(der)
        except Exception:
            logger.debug("Failed to extract peer certificate", exc_info=True)

    @property
    def used_cert_multihash(self) -> bytes | None:
        return self._used_cert_multihash

    # ------------------------------------------------------------------
    # Client / server session setup helpers
    # ------------------------------------------------------------------

    async def wait_handshake(self, timeout: float | None = None) -> None:
        timeout = timeout if timeout is not None else self._config.handshake_timeout
        with trio.move_on_after(timeout) as scope:
            await self._handshake_completed.wait()
        if scope.cancelled_caught:
            raise WebTransportConnectionError("QUIC handshake timed out")

    async def client_open_session(self, authority: str) -> WebTransportStream:
        """Send H3 CONNECT and open the Noise WebTransport stream."""
        await self.wait_handshake()
        assert self._h3 is not None
        path = self._config.well_known_path
        stream_id = self._quic.get_next_available_stream_id()
        self._h3.send_headers(
            stream_id=stream_id,
            headers=[
                (b":method", b"CONNECT"),
                (b":protocol", b"webtransport"),
                (b":scheme", b"https"),
                (b":path", path.encode("utf-8")),
                (b":authority", authority.encode("utf-8")),
            ],
        )
        self._session_id = stream_id
        # Spec: client may start Noise without waiting for CONNECT response.
        noise_stream_id = self._h3.create_webtransport_stream(
            session_id=stream_id, is_unidirectional=False
        )
        _mark_local_webtransport_stream(self._h3, noise_stream_id, stream_id)
        noise_stream = WebTransportStream(self, noise_stream_id, is_initiator=True)
        async with self._stream_lock:
            self._streams[noise_stream_id] = noise_stream
        self._noise_stream_id = noise_stream_id
        await self.transmit()
        return noise_stream

    async def server_wait_session_and_noise_stream(
        self, timeout: float | None = None
    ) -> WebTransportStream:
        """Wait for CONNECT accept + first client WT stream (Noise)."""
        timeout = timeout if timeout is not None else self._config.handshake_timeout
        with trio.move_on_after(timeout) as scope:
            await self._connect_accepted.wait()
            await self._first_wt_stream.wait()
        if scope.cancelled_caught:
            raise WebTransportConnectionError(
                "Timed out waiting for WebTransport session / Noise stream"
            )
        assert self._noise_stream_id is not None
        stream = self._streams[self._noise_stream_id]
        return stream

    async def _send_stream_data(
        self, stream_id: int, data: bytes, end_stream: bool = False
    ) -> None:
        self._quic.send_stream_data(stream_id, data, end_stream=end_stream)
        await self.transmit()

    async def _reset_stream(self, stream_id: int) -> None:
        try:
            self._quic.reset_stream(
                stream_id, error_code=QuicErrorCode.STREAM_STATE_ERROR
            )
            await self.transmit()
        except Exception:
            pass

    def set_remote_peer_id(self, peer_id: ID) -> None:
        self._remote_peer_id = peer_id
        self.peer_id = peer_id


def make_client_quic_config(config: WebTransportConfig) -> QuicConfiguration:
    conf = QuicConfiguration(
        is_client=True,
        alpn_protocols=H3_ALPN,
        verify_mode=ssl.CERT_NONE,
        max_datagram_frame_size=config.max_datagram_frame_size,
        idle_timeout=config.idle_timeout,
    )
    return conf


def make_server_quic_config(config: WebTransportConfig) -> QuicConfiguration:
    conf = QuicConfiguration(
        is_client=False,
        alpn_protocols=H3_ALPN,
        verify_mode=ssl.CERT_NONE,
        max_datagram_frame_size=config.max_datagram_frame_size,
        idle_timeout=config.idle_timeout,
    )
    config.get_or_create_cert_manager().apply_to_quic_configuration(conf)
    return conf


def parse_dest_cid(data: bytes, host_cid_length: int = 8) -> bytes | None:
    """Extract destination connection ID from a QUIC packet."""
    try:
        buf = Buffer(data=data)
        header = pull_quic_header(buf, host_cid_length=host_cid_length)
        return bytes(header.destination_cid)
    except Exception:
        return None
