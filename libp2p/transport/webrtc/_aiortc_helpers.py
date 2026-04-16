"""
aiortc integration helpers for the WebRTC transport.

All direct ``aiortc`` imports are isolated here so the rest of the
``libp2p.transport.webrtc`` package remains aiortc-free and testable
without the optional dependency.

Functions in this module run on the **asyncio** event loop (via
:class:`AsyncioBridge`).  They should never be called directly from
trio code — always go through ``bridge.run_coro(...)``.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import TYPE_CHECKING, Any

from aiortc import (
    RTCConfiguration,
    RTCPeerConnection,
)
from aiortc.rtcdtlstransport import RTCCertificate

if TYPE_CHECKING:
    from .connection import WebRTCConnection

logger = logging.getLogger(__name__)

# Timeout for ICE connection establishment (seconds).
_ICE_CONNECT_TIMEOUT = 30.0

# Timeout for HTTP SDP exchange (seconds).
_SDP_HTTP_TIMEOUT = 15.0


# ------------------------------------------------------------------
# Peer-connection lifecycle
# ------------------------------------------------------------------


async def create_peer_connection(
    rtc_cert: RTCCertificate,
    ice_servers: list[str] | None = None,
) -> RTCPeerConnection:
    """
    Create an ``RTCPeerConnection`` with the given certificate.

    Must run on the asyncio bridge loop because aiortc's
    ``RTCPeerConnection.__init__`` calls ``asyncio.get_event_loop()``
    internally to schedule ICE initialization.

    :param rtc_cert: An aiortc certificate
        (from ``WebRTCCertificate._rtc_certificate``).
    :param ice_servers: Optional STUN/TURN server URLs.
    :returns: A new peer connection.
    """
    config = RTCConfiguration(certificates=[rtc_cert])  # type: ignore[call-arg]
    return RTCPeerConnection(configuration=config)


async def create_noise_channel(pc: RTCPeerConnection) -> Any:
    """
    Create a negotiated data channel with ID 0 for the Noise handshake.

    Both sides must call this with the same ``id`` and ``negotiated=True``
    so the channel is available without SDP renegotiation.
    """
    return pc.createDataChannel("noise", negotiated=True, id=0)


async def wait_for_connected(
    pc: RTCPeerConnection,
    timeout: float = _ICE_CONNECT_TIMEOUT,
) -> None:
    """
    Wait until the peer connection reaches the ``connected`` state.

    :raises TimeoutError: If the connection doesn't complete in time.
    :raises ConnectionError: If the connection enters ``failed`` or ``closed``.
    """
    if pc.connectionState == "connected":
        return

    connected = asyncio.Event()
    failed = asyncio.Event()

    @pc.on("connectionstatechange")
    def _on_state_change() -> None:
        state = pc.connectionState
        logger.debug("ICE connection state: %s", state)
        if state == "connected":
            connected.set()
        elif state in ("failed", "closed"):
            failed.set()

    try:
        done, pending = await asyncio.wait(
            [
                asyncio.ensure_future(_event_wait(connected)),
                asyncio.ensure_future(_event_wait(failed)),
            ],
            timeout=timeout,
            return_when=asyncio.FIRST_COMPLETED,
        )
        # Cancel any pending tasks to avoid leaks on the asyncio loop.
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        if not done:
            raise TimeoutError(f"ICE connection did not complete within {timeout}s")
        if failed.is_set():
            raise ConnectionError(f"ICE connection failed (state={pc.connectionState})")
    finally:
        # Clean up the listener to avoid leaks
        pc.remove_all_listeners("connectionstatechange")


async def _event_wait(event: asyncio.Event) -> None:
    """Thin wrapper so ``asyncio.wait`` can track an Event."""
    await event.wait()


def get_remote_fingerprint(pc: RTCPeerConnection) -> bytes:
    """
    Extract the remote DTLS certificate's SHA-256 fingerprint.

    Must be called after the DTLS handshake completes (i.e. after ICE
    reaches ``connected``).

    :returns: 32-byte SHA-256 digest.
    :raises ValueError: If the remote certificate is not available.
    """
    dtls = getattr(pc, "_dtlsTransport", None)
    if dtls is None:
        raise ValueError("DTLS transport not available on peer connection")
    remote_cert = getattr(dtls, "_remote_certificate", None)
    if remote_cert is None:
        raise ValueError("Remote DTLS certificate not available")
    # remote_cert is a cryptography x509.Certificate
    from cryptography.hazmat.primitives.serialization import Encoding

    der = remote_cert.public_bytes(Encoding.DER)
    return hashlib.sha256(der).digest()


# ------------------------------------------------------------------
# Callback wiring
# ------------------------------------------------------------------


def wire_pc_to_connection(
    pc: RTCPeerConnection,
    conn: WebRTCConnection,
) -> None:
    """
    Wire aiortc callbacks to a :class:`WebRTCConnection`.

    Sets the three callback slots and registers ``on_datachannel`` /
    ``on_message`` / ``on_close`` event handlers that route into the
    connection's thread-safe methods.
    """
    # Track open channels so _send_on_channel_cb can find them.
    channels: dict[int, Any] = {}

    async def _create_channel(channel_id: int, label: str) -> None:
        ch = pc.createDataChannel(label or "", negotiated=True, id=channel_id)
        channels[channel_id] = ch
        _bind_channel_events(ch, channel_id, conn)

    async def _send_on_channel(channel_id: int, data: bytes) -> None:
        ch = channels.get(channel_id)
        if ch is not None:
            ch.send(data)

    async def _close_pc() -> None:
        await pc.close()

    conn._create_channel_cb = _create_channel
    conn._send_on_channel_cb = _send_on_channel
    conn._close_pc_cb = _close_pc

    @pc.on("datachannel")
    def _on_datachannel(channel: Any) -> None:
        ch_id = channel.id if channel.id is not None else len(channels)
        channels[ch_id] = channel
        conn.on_datachannel(ch_id)
        _bind_channel_events(channel, ch_id, conn)


def _bind_channel_events(
    channel: Any,
    channel_id: int,
    conn: WebRTCConnection,
) -> None:
    """Bind message/close events on a single data channel."""

    @channel.on("message")  # type: ignore[misc,untyped-decorator]
    def _on_message(message: str | bytes) -> None:
        data = message if isinstance(message, bytes) else message.encode()
        conn.on_channel_message(channel_id, data)

    @channel.on("close")  # type: ignore[misc,untyped-decorator]
    def _on_close() -> None:
        conn.on_channel_closed(channel_id)


# ------------------------------------------------------------------
# Noise-channel helpers
# ------------------------------------------------------------------


def make_noise_channel_callbacks(
    channel: Any,
) -> tuple[Any, Any, asyncio.Queue[bytes]]:
    """
    Wire a data channel for the Noise handshake.

    :returns: ``(send_fn, recv_fn, recv_queue)`` — async callables for
        sending/receiving bytes, and the underlying queue.
    """
    recv_queue: asyncio.Queue[bytes] = asyncio.Queue()

    @channel.on("message")  # type: ignore[misc,untyped-decorator]
    def _on_noise_msg(message: str | bytes) -> None:
        data = message if isinstance(message, bytes) else message.encode()
        recv_queue.put_nowait(data)

    async def send(data: bytes) -> None:
        channel.send(data)

    async def recv() -> bytes:
        return await recv_queue.get()

    return send, recv, recv_queue


# ------------------------------------------------------------------
# HTTP-based SDP signaling (raw asyncio, no aiohttp dependency)
# ------------------------------------------------------------------


async def run_signaling_server(
    host: str,
    port: int,
    on_offer: Any,  # async (offer_sdp: str) -> str (answer_sdp)
) -> asyncio.Server:
    """
    Start a minimal HTTP server that accepts SDP offers via ``POST /sdp``.

    :param host: Bind address.
    :param port: Bind port (TCP).
    :param on_offer: Async callback ``(offer_sdp) -> answer_sdp``.
    :returns: The running :class:`asyncio.Server`.
    """

    async def _handle(
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            # Read HTTP request line (consumed but not used) + headers
            await asyncio.wait_for(reader.readline(), timeout=_SDP_HTTP_TIMEOUT)
            headers: dict[str, str] = {}
            while True:
                line = await asyncio.wait_for(
                    reader.readline(), timeout=_SDP_HTTP_TIMEOUT
                )
                if line in (b"\r\n", b"\n", b""):
                    break
                key, _, value = line.decode().partition(":")
                headers[key.strip().lower()] = value.strip()

            content_length = int(headers.get("content-length", "0"))
            body = b""
            if content_length > 0:
                body = await asyncio.wait_for(
                    reader.readexactly(content_length),
                    timeout=_SDP_HTTP_TIMEOUT,
                )

            # Process: call the offer handler, get answer SDP
            answer_sdp = await on_offer(body.decode())
            answer_bytes = answer_sdp.encode()

            # Send HTTP response
            response = (
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: application/sdp\r\n"
                b"Content-Length: " + str(len(answer_bytes)).encode() + b"\r\n"
                b"\r\n"
            ) + answer_bytes
            writer.write(response)
            await writer.drain()
        except Exception as e:
            logger.debug("Signaling server error: %s", e)
            try:
                writer.write(b"HTTP/1.1 500 Internal Server Error\r\n\r\n")
                await writer.drain()
            except Exception:
                pass
        finally:
            writer.close()

    server = await asyncio.start_server(_handle, host, port)
    logger.info("WebRTC signaling HTTP server listening on %s:%d", host, port)
    return server


async def post_sdp(
    host: str,
    port: int,
    offer_sdp: str,
    timeout: float = _SDP_HTTP_TIMEOUT,
) -> str:
    """
    POST an SDP offer to a WebRTC Direct listener and return the answer.

    :param host: Listener IP address.
    :param port: Listener TCP port (same number as the UDP port in the multiaddr).
    :param offer_sdp: The SDP offer string.
    :param timeout: HTTP timeout in seconds.
    :returns: The SDP answer string.
    :raises ConnectionError: If the HTTP exchange fails.
    """
    offer_bytes = offer_sdp.encode()
    request = (
        b"POST /sdp HTTP/1.1\r\n"
        b"Host: " + f"{host}:{port}".encode() + b"\r\n"
        b"Content-Type: application/sdp\r\n"
        b"Content-Length: " + str(len(offer_bytes)).encode() + b"\r\n"
        b"\r\n"
    ) + offer_bytes

    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
        writer.write(request)
        await writer.drain()

        # Read response status line
        status_line = await asyncio.wait_for(reader.readline(), timeout=timeout)
        if b"200" not in status_line:
            raise ConnectionError(
                f"SDP exchange failed: {status_line.decode().strip()}"
            )

        # Read headers
        headers: dict[str, str] = {}
        while True:
            line = await asyncio.wait_for(reader.readline(), timeout=timeout)
            if line in (b"\r\n", b"\n", b""):
                break
            key, _, value = line.decode().partition(":")
            headers[key.strip().lower()] = value.strip()

        content_length = int(headers.get("content-length", "0"))
        body = await asyncio.wait_for(
            reader.readexactly(content_length), timeout=timeout
        )
        writer.close()
        return body.decode()
    except asyncio.TimeoutError as e:
        raise ConnectionError(f"SDP exchange timed out after {timeout}s") from e
    except Exception as e:
        raise ConnectionError(f"SDP exchange failed: {e}") from e
