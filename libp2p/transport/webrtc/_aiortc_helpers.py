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
    RTCIceServer,
    RTCPeerConnection,
)
from aiortc.rtcdtlstransport import RTCCertificate

from .exceptions import WebRTCStreamError

if TYPE_CHECKING:
    from ._udp_mux import UdpMux
    from .connection import WebRTCConnection

logger = logging.getLogger(__name__)

# Timeout for ICE connection establishment (seconds).
_ICE_CONNECT_TIMEOUT = 30.0

# Timeout for HTTP SDP exchange (seconds).
_SDP_HTTP_TIMEOUT = 15.0

# Bounds for the experimental HTTP /sdp harness (config.enable_sdp_http_harness,
# off by default; the spec path is the STUN listener) — defend against
# memory-amplification DoS whenever it is enabled.
_MAX_SDP_BODY_SIZE = 32 * 1024  # 32 KiB; SDP offers are typically 1–4 KiB
_MAX_HEADER_LINES = 64
_MAX_HEADER_BYTES = 8 * 1024  # 8 KiB total across all header lines


# ------------------------------------------------------------------
# Peer-connection lifecycle
# ------------------------------------------------------------------


async def create_peer_connection(
    rtc_cert: RTCCertificate,
    ice_servers: list[str] | None = None,
) -> RTCPeerConnection:
    """
    Create an ``RTCPeerConnection`` pinned to the given certificate.

    Must run on the asyncio bridge loop because aiortc's
    ``RTCPeerConnection.__init__`` calls ``asyncio.get_event_loop()``
    internally to schedule ICE initialization.

    aiortc >= 1.5 no longer accepts ``certificates=`` in
    :class:`RTCConfiguration` — passing it raises ``TypeError``.  We
    build the peer connection with ICE servers only, then replace the
    auto-generated DTLS certificate before any SDP operation triggers
    the DTLS handshake.  The fingerprint and the actual handshake cert
    are read from a name-mangled private attribute
    (``self.__certificates`` inside ``RTCPeerConnection`` →
    ``self._RTCPeerConnection__certificates`` from the outside —
    see ``aiortc/rtcpeerconnection.py:295,1129``).  Setting the
    un-mangled ``pc._certificates`` is a no-op that aiortc never reads.

    :param rtc_cert: An aiortc certificate
        (from ``WebRTCCertificate._rtc_certificate``).
    :param ice_servers: Optional STUN/TURN server URLs.
    :returns: A new peer connection.
    """
    ice_server_list = (
        [RTCIceServer(urls=[url]) for url in ice_servers] if ice_servers else []
    )
    config = RTCConfiguration(iceServers=ice_server_list)
    pc = RTCPeerConnection(configuration=config)
    # Replace aiortc's auto-generated cert.  Must use the mangled name —
    # aiortc reads only `self.__certificates`, which mangles to this.
    set_private_attr(pc, "_RTCPeerConnection__certificates", [rtc_cert])
    return pc


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

    @pc.on("connectionstatechange")  # type: ignore[misc,untyped-decorator]
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
    # aiortc keeps one DTLS transport per SCTP association; for a
    # data-channel-only PC that is ``pc.sctp.transport``.  The peer cert
    # lives on the pyOpenSSL connection once the handshake completed.
    sctp = getattr(pc, "sctp", None)
    dtls = getattr(sctp, "transport", None) if sctp is not None else None
    if dtls is None:
        raise ValueError("DTLS transport not available on peer connection")
    ssl_conn = getattr(dtls, "_ssl", None)
    if ssl_conn is None:
        raise ValueError("DTLS handshake has not started")
    remote_cert = ssl_conn.get_peer_certificate(as_cryptography=True)
    if remote_cert is None:
        raise ValueError("Remote DTLS certificate not available")
    # remote_cert is a cryptography x509.Certificate
    from cryptography.hazmat.primitives.serialization import Encoding

    der = remote_cert.public_bytes(Encoding.DER)
    return hashlib.sha256(der).digest()


def set_private_attr(obj: Any, name: str, value: Any) -> None:
    """
    Overwrite a private (possibly name-mangled) library attribute.

    Writing a wrong — or upgraded-away — name would silently create a new
    attribute the library never reads; asserting existence first turns that
    silent no-op into a failure at the line that caused it, and fails loudly
    on the aiortc/aioice upgrade that renames or drops the slot. It separates
    "wrote to the wrong name" from "the value never reached the handshake"
    (which only the downstream invariant tests would catch).
    """
    assert hasattr(obj, name), f"{type(obj).__name__} has no attribute {name!r}"
    setattr(obj, name, value)


def force_listener_dtls_server_role(pc: RTCPeerConnection) -> None:
    """
    Make a WebRTC-Direct listener answer as DTLS server (``a=setup:passive``).

    Inferred offers use ``a=setup:actpass`` per spec. aiortc's
    :meth:`RTCPeerConnection.createAnswer` defaults to DTLS *client* when the
    transport role is still ``auto`` after an ``actpass`` offer — see
    ``rtcpeerconnection.createAnswer`` lines that map ``auto`` → ``client``.
    """
    sctp = getattr(pc, "sctp", None)
    dtls = getattr(sctp, "transport", None) if sctp is not None else None
    if dtls is None:
        raise ValueError("DTLS transport not available on peer connection")
    dtls._set_role("server")


# ------------------------------------------------------------------
# Peer-connection shutdown
# ------------------------------------------------------------------


def _abort_ice_transports(pc: RTCPeerConnection) -> None:
    """Force-close the aioice UDP transports of a data-channel-only *pc*."""
    sctp = getattr(pc, "sctp", None)
    dtls = getattr(sctp, "transport", None) if sctp is not None else None
    ice = getattr(dtls, "transport", None) if dtls is not None else None
    conn = getattr(ice, "_connection", None) if ice is not None else None
    for proto in list(getattr(conn, "_protocols", [])):
        abort = getattr(getattr(proto, "transport", None), "abort", None)
        if abort is not None:
            abort()


async def close_peer_connection(pc: RTCPeerConnection, timeout: float = 5.0) -> None:
    """
    Close *pc*, working around a Windows proactor close hang.

    When a datagram send is still in flight as ``transport.close()`` runs
    (typical: DTLS just queued its close_notify), CPython's
    ``_ProactorDatagramTransport._loop_writing`` early-returns on
    ``_conn_lost`` and the deferred ``connection_lost`` is never delivered,
    so aioice's ``StunProtocol.close()`` awaits its closed-future forever
    (observed deterministically on Windows CPython 3.12/3.13). On timeout,
    ``abort()`` the lingering transports — ``_force_close`` delivers
    ``connection_lost`` unconditionally — and let ``close()`` finish.
    """
    task = asyncio.ensure_future(pc.close())
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout)
        return
    except asyncio.TimeoutError:
        logger.debug("pc.close() stalled; aborting ICE transports")
    _abort_ice_transports(pc)
    try:
        await asyncio.wait_for(task, timeout)
    except asyncio.TimeoutError:
        task.cancel()
        logger.warning("pc.close() still stalled after transport abort")


# ------------------------------------------------------------------
# UdpMux bridge
# ------------------------------------------------------------------


def attach_muxed_connection(pc: RTCPeerConnection, mux: UdpMux, conn: Any) -> None:
    """
    Run *pc*'s ICE over the :class:`UdpMux`-backed ``aioice.Connection`` *conn*.

    aiortc offers no injection point for an external ICE connection: the
    gatherer builds its own ``aioice.Connection`` when the SCTP/DTLS/ICE
    stack is created (synchronously, on the first ``createDataChannel``).
    This swaps that connection for *conn* — created via
    :meth:`UdpMux.add_ice_connection` — so the peer connection sends and
    receives on the shared UDP port instead of binding its own.

    Call **after** ``createDataChannel`` and **before** any
    ``set*Description``. Touches aiortc/aioice privates (validated against
    aiortc 1.15 / aioice 0.10):

    - ``iceGatherer._connection`` / ``iceTransport._connection`` — what
      ``getLocalParameters()`` / ``getLocalCandidates()`` / ``start()`` use;
    - ``iceTransport._recv`` / ``_send`` — bound at construction to the
      *original* connection's methods and used by ``RTCDtlsTransport``;
      forgetting these leaves DTLS talking to the orphaned connection.

    The orphaned original connection never bound a socket (gathering is
    triggered later, and *conn* has it marked done), so it is simply dropped.
    ``RTCIceTransport.stop()`` closes *conn*, which the mux tolerates. On
    ICE ``completed`` the nominated remote address is registered on the mux
    (belt and braces — the mux already learns it from the peer's STUN checks);
    on ``closed``/``failed`` the connection's ufrag and addresses are dropped.
    """
    sctp = pc.sctp
    if sctp is None:
        raise ValueError("call pc.createDataChannel() before attach_muxed_connection")
    ice = (
        sctp.transport.transport
    )  # RTCSctpTransport -> RTCDtlsTransport -> RTCIceTransport
    set_private_attr(ice.iceGatherer, "_connection", conn)
    set_private_attr(ice, "_connection", conn)
    set_private_attr(ice, "_recv", conn.recv)
    set_private_attr(ice, "_send", conn.send)

    ufrag = conn.local_username

    @ice.on("statechange")  # type: ignore[misc,untyped-decorator]
    def _on_ice_state() -> None:
        state = ice.state
        if state == "completed":
            pair = conn._nominated.get(1)
            if pair is not None:
                mux.register_addr(pair.remote_addr, pair.protocol)
        elif state in ("closed", "failed"):
            mux.unregister(ufrag)


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
    # Track open channels so _send_on_channel_cb can find them.  Keyed by
    # the libp2p-local channel id (the conn's outbound/inbound counter),
    # NOT by aiortc's SCTP channel.id.  These two id spaces are disjoint
    # by design: outbound = even, inbound = odd.
    channels: dict[int, Any] = {}

    async def _create_channel(channel_id: int, label: str) -> None:
        # In-band channel: drop `negotiated=True, id=`.  aiortc opens an
        # SCTP DCEP-negotiated channel; the peer's `datachannel` event
        # fires (which is what makes accept_stream() unblock).  The
        # libp2p `channel_id` is a local routing key only and never
        # crosses the wire.
        ch = pc.createDataChannel(label or f"stream-{channel_id}")
        channels[channel_id] = ch
        _bind_channel_events(ch, channel_id, conn)

    async def _send_on_channel(channel_id: int, data: bytes) -> None:
        ch = channels.get(channel_id)
        if ch is None:
            return
        # aiortc's RTCDataChannel raises InvalidStateError if send() is
        # called while the channel is still in "connecting".  For
        # in-band channels there's a real window between createDataChannel
        # (when open_stream() returns) and the SCTP+DCEP open event;
        # any caller that writes immediately would hit it.  Wait once;
        # after the channel opens this is a fast readyState check.
        if ch.readyState != "open":
            await _wait_channel_open(ch)
        ch.send(data)

    async def _close_pc() -> None:
        await close_peer_connection(pc)

    conn._create_channel_cb = _create_channel
    conn._send_on_channel_cb = _send_on_channel
    conn._close_pc_cb = _close_pc

    @pc.on("datachannel")  # type: ignore[misc,untyped-decorator]
    def _on_datachannel(channel: Any) -> None:
        # Remote opened an in-band channel.  Allocate a fresh libp2p id
        # in our inbound (odd) space; we never use channel.id from SCTP
        # because that would risk colliding with our outbound (even) ids.
        try:
            channel_id = conn._allocate_inbound_id()
        except WebRTCStreamError as exc:
            # At max_concurrent_streams.  If we did nothing the new channel
            # would sit open with no handlers, the remote would assume it
            # works, and writes would silently disappear into the void.
            # Close it instead so the remote sees the rejection.
            logger.warning("Rejecting inbound data channel (%s); closing.", exc)
            try:
                channel.close()
            except Exception:
                logger.debug("Error closing rejected inbound channel", exc_info=True)
            return
        channels[channel_id] = channel
        # Bind message/close handlers BEFORE notifying the connection.
        # aiortc may have already buffered the channel's `open` event,
        # and any early message would otherwise race past on_datachannel.
        _bind_channel_events(channel, channel_id, conn)
        conn.on_datachannel(channel_id)


# Bound on how long _wait_channel_open will block.  Matches the ICE
# connect ceiling — if SCTP DCEP hasn't opened the channel by then,
# something is wedged and we want the trio caller to learn about it
# rather than hang on bridge.run_coro forever.
_CHANNEL_OPEN_TIMEOUT = 30.0


async def _wait_channel_open(ch: Any, timeout: float = _CHANNEL_OPEN_TIMEOUT) -> None:
    """
    Block until *ch* reaches ``readyState == "open"``, or fail if it
    terminally closes / the wait times out.  Runs on the asyncio loop.
    """
    if ch.readyState == "open":
        return
    if ch.readyState in ("closing", "closed"):
        raise WebRTCStreamError(f"data channel never opened (state={ch.readyState})")

    opened = asyncio.Event()
    closed = asyncio.Event()

    @ch.on("open")  # type: ignore[misc,untyped-decorator]
    def _on_open() -> None:
        opened.set()

    @ch.on("close")  # type: ignore[misc,untyped-decorator]
    def _on_close() -> None:
        closed.set()

    # Re-check after handler registration to avoid losing an "open"
    # event that fired between the early-return check above and now.
    if ch.readyState == "open":
        return

    open_task = asyncio.ensure_future(opened.wait())
    closed_task = asyncio.ensure_future(closed.wait())
    try:
        try:
            await asyncio.wait_for(
                asyncio.wait(
                    [open_task, closed_task],
                    return_when=asyncio.FIRST_COMPLETED,
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            raise WebRTCStreamError(
                f"data channel did not open within {timeout}s (state={ch.readyState})"
            ) from None
    finally:
        for task in (open_task, closed_task):
            if not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass

    if closed.is_set():
        raise WebRTCStreamError("data channel closed before it could open")


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
        # The negotiated channel exists before SCTP is up; aiortc raises
        # InvalidStateError on send() until it is "open".  The Noise
        # initiator (the listener) sends first, right after DTLS connects,
        # so wait here rather than in every caller.
        await _wait_channel_open(channel)
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
            # Request line (consumed but not validated)
            await asyncio.wait_for(reader.readline(), timeout=_SDP_HTTP_TIMEOUT)

            # Headers — bounded by line count and accumulated byte size.
            # The for/else fires when the loop exhausts the reads without
            # finding the blank-line terminator.  We read _MAX_HEADER_LINES + 1
            # times so the last read can be the blank terminator after a full
            # _MAX_HEADER_LINES header lines (otherwise the effective cap would
            # be one below the named constant).
            headers: dict[str, str] = {}
            header_bytes = 0
            for _ in range(_MAX_HEADER_LINES + 1):
                line = await asyncio.wait_for(
                    reader.readline(), timeout=_SDP_HTTP_TIMEOUT
                )
                if line in (b"\r\n", b"\n", b""):
                    break
                header_bytes += len(line)
                if header_bytes > _MAX_HEADER_BYTES:
                    writer.write(
                        b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n"
                    )
                    await writer.drain()
                    return
                key, _, value = line.decode().partition(":")
                headers[key.strip().lower()] = value.strip()
            else:
                writer.write(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n")
                await writer.drain()
                return

            # Validate Content-Length before touching any body buffer.
            raw_cl = headers.get("content-length", "0")
            try:
                content_length = int(raw_cl)
            except ValueError:
                writer.write(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n")
                await writer.drain()
                return
            if content_length < 0:
                writer.write(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n")
                await writer.drain()
                return
            if content_length > _MAX_SDP_BODY_SIZE:
                writer.write(
                    b"HTTP/1.1 413 Payload Too Large\r\nContent-Length: 0\r\n\r\n"
                )
                await writer.drain()
                return

            body = b""
            if content_length > 0:
                body = await asyncio.wait_for(
                    reader.readexactly(content_length),
                    timeout=_SDP_HTTP_TIMEOUT,
                )

            answer_sdp = await on_offer(body.decode())
            answer_bytes = answer_sdp.encode()
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
