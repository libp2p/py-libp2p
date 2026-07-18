"""
Integration test: two real ``RTCPeerConnection``s, end-to-end loopback.

Validates the WebRTC data-channel layer at the wire level — the three
ecosystem-compatibility fixes documented in PR #1309 review notes:

  - **In-band data channels** (``negotiated=False``): the responder's
    ``datachannel`` event must fire so :py:meth:`WebRTCConnection.accept_stream`
    unblocks.  With ``negotiated=True`` the peer never sees the event.
  - **uvarint length-prefixed framing**: every send must stay within the
    16 KiB spec ceiling, large writes chunk at :data:`MAX_PAYLOAD_SIZE`,
    and a ``> 16 KiB`` payload round-trips byte-for-byte through chunking
    and reassembly.
  - **DTLS certificate pinning**: aiortc >= 1.5 dropped ``certificates=`` in
    ``RTCConfiguration``; the cert override must take effect before
    ``createOffer`` / ``createAnswer`` so the local DTLS fingerprint in
    the SDP matches the one our peer expects.

This test deliberately skips Noise — Noise has separate integration
coverage and lives on top of an established connection.  Here we drive
the data-channel layer directly.

Requires ``aiortc`` to be installed (``pip install 'libp2p[webrtc]'``).
Skipped automatically otherwise.
"""
# pyrefly: ignore

from __future__ import annotations

import pytest
import trio

try:
    import aiortc  # noqa: F401

    HAS_AIORTC = True
except ImportError:
    HAS_AIORTC = False

from libp2p.peer.id import ID
from libp2p.transport.webrtc._asyncio_bridge import AsyncioBridge
from libp2p.transport.webrtc.certificate import WebRTCCertificate
from libp2p.transport.webrtc.connection import WebRTCConnection
from libp2p.transport.webrtc.constants import MAX_PAYLOAD_SIZE

pytestmark = pytest.mark.skipif(not HAS_AIORTC, reason="aiortc not installed")


def _sdp_fingerprint_string(cert: WebRTCCertificate) -> str:
    """
    Render *cert*'s SHA-256 fingerprint in the colon-separated upper-hex
    form aiortc writes into SDP ``a=fingerprint:sha-256 ...`` lines.
    """
    return ":".join(f"{b:02X}" for b in cert.fingerprint)


async def _setup_loopback(
    bridge: AsyncioBridge,
) -> tuple[WebRTCConnection, WebRTCConnection, WebRTCCertificate, WebRTCCertificate]:
    """
    Build two ICE-connected ``WebRTCConnection``s sharing one bridge.

    Each peer gets its own DTLS certificate (pinned via
    ``create_peer_connection`` — fix 3) and an in-memory SDP exchange.
    Returns ``(initiator_conn, responder_conn)`` after both peer
    connections reach ``connected`` state.
    """
    from aiortc import RTCSessionDescription

    from libp2p.transport.webrtc._aiortc_helpers import (
        create_peer_connection,
        wait_for_connected,
        wire_pc_to_connection,
    )

    cert_a = WebRTCCertificate.from_aiortc()
    cert_b = WebRTCCertificate.from_aiortc()

    # ice_servers=[] keeps loopback fast — no STUN round trip needed
    # when host candidates already cover 127.0.0.1.
    pc_a = await bridge.run_coro(
        create_peer_connection(cert_a._rtc_certificate, ice_servers=[])
    )
    pc_b = await bridge.run_coro(
        create_peer_connection(cert_b._rtc_certificate, ice_servers=[])
    )

    conn_a = WebRTCConnection(
        peer_id=ID(b"\x00" * 32),
        bridge=bridge,
        is_initiator=True,
    )
    conn_b = WebRTCConnection(
        peer_id=ID(b"\x00" * 32),
        bridge=bridge,
        is_initiator=False,
    )
    wire_pc_to_connection(pc_a, conn_a)
    wire_pc_to_connection(pc_b, conn_b)

    # SDP needs an SCTP m-line — that requires at least one
    # createDataChannel call on the offerer BEFORE createOffer.  Opening
    # a stream now queues an in-band channel that will actually open
    # once SCTP is up.  We return the stream alongside the connections
    # so the test doesn't need to re-open.
    async def _exchange() -> None:
        offer = await pc_a.createOffer()
        await pc_a.setLocalDescription(offer)
        await pc_b.setRemoteDescription(
            RTCSessionDescription(
                sdp=pc_a.localDescription.sdp,
                type=pc_a.localDescription.type,
            )
        )
        answer = await pc_b.createAnswer()
        await pc_b.setLocalDescription(answer)
        await pc_a.setRemoteDescription(
            RTCSessionDescription(
                sdp=pc_b.localDescription.sdp,
                type=pc_b.localDescription.type,
            )
        )

    # The initiator's createDataChannel must happen BEFORE createOffer
    # so the SCTP m-line is in the offer.  open_stream() does that via
    # the wired _create_channel_cb.
    await conn_a.open_stream()

    await bridge.run_coro(_exchange())

    async def _wait_both() -> None:
        import asyncio as _asyncio

        await _asyncio.gather(
            wait_for_connected(pc_a, timeout=15.0),
            wait_for_connected(pc_b, timeout=15.0),
        )

    await bridge.run_coro(_wait_both())

    await conn_a.start()
    await conn_b.start()
    return conn_a, conn_b, cert_a, cert_b


async def _drain(stream: object, total: int) -> bytes:
    """Read exactly *total* bytes from *stream* (handles short reads)."""
    buf = bytearray()
    while len(buf) < total:
        chunk = await stream.read(total - len(buf))  # type: ignore[attr-defined]
        if not chunk:
            raise AssertionError(
                f"stream EOF before draining {total} bytes (got {len(buf)})"
            )
        buf.extend(chunk)
    return bytes(buf)


@pytest.mark.trio
async def test_cert_pinning_lands_in_sdp_fingerprint() -> None:
    """
    Guards against a class of cert-pin bug: if the pin is a no-op (e.g.
    written to a public attribute aiortc never reads because it actually
    stores the cert under a name-mangled private slot), the SDP ``a=fingerprint``
    line reflects aiortc's auto-generated cert instead of ours.

    A regression here means every real ``/webrtc-direct/certhash/...`` dial
    would fail with "Remote DTLS fingerprint does not match certhash" — but
    the loopback echo path would still pass without this assertion, because
    it doesn't validate fingerprints against the multiaddr.
    """
    from libp2p.transport.webrtc._aiortc_helpers import create_peer_connection

    bridge = AsyncioBridge()
    await bridge.start()
    try:
        cert = WebRTCCertificate.from_aiortc()
        pc = await bridge.run_coro(
            create_peer_connection(cert._rtc_certificate, ice_servers=[])
        )

        # Need at least one data channel for the SCTP m-line, otherwise
        # createOffer omits the DTLS fingerprint entirely.
        await bridge.run_coro(_create_dummy_channel(pc))

        async def _offer() -> str:
            offer = await pc.createOffer()
            await pc.setLocalDescription(offer)
            return pc.localDescription.sdp

        sdp = await bridge.run_coro(_offer())
        expected = _sdp_fingerprint_string(cert)
        assert expected in sdp.upper(), (
            f"SDP fingerprint does not match pinned cert.\n"
            f"  pinned cert fingerprint: {expected}\n"
            f"  SDP (uppercase): {sdp.upper()[:600]}..."
        )
    finally:
        await bridge.stop()


async def _create_dummy_channel(pc: object) -> None:
    """Create a no-op data channel so the offer includes an SCTP m-line."""
    pc.createDataChannel("_fingerprint_assertion_only")  # type: ignore[attr-defined]


@pytest.mark.trio
async def test_open_accept_echo_large_payload() -> None:
    """
    End-to-end: open a stream, accept it on the peer, echo a payload that
    crosses the chunk boundary (forces multi-frame send + reassembly).

    The payload is intentionally larger than :data:`MAX_PAYLOAD_SIZE` so
    the test fails closed if the chunking math regresses (e.g. someone
    re-introduces chunks at ``MAX_MESSAGE_SIZE`` and pushes the wire over
    16 KiB, or drops the uvarint prefix and the receiver tries to parse
    a bare protobuf).
    """
    async with trio.open_nursery() as nursery:
        bridge = AsyncioBridge()
        await bridge.start()

        async def _run() -> None:
            try:
                conn_a, conn_b, _cert_a, _cert_b = await _setup_loopback(bridge)
                # conn_a already has the stream open (from setup)
                stream_a = list(conn_a._streams.values())[0]
                stream_b = await conn_b.accept_stream()

                payload = (bytes(range(256)) * (MAX_PAYLOAD_SIZE // 256 + 2))[
                    : MAX_PAYLOAD_SIZE + 4096
                ]
                assert (
                    len(payload) > MAX_PAYLOAD_SIZE
                ), "payload must cross the chunk boundary to exercise framing"

                # A → B
                await stream_a.write(payload)
                got_b = await _drain(stream_b, len(payload))
                assert got_b == payload, "A→B payload corrupted"

                # B → A (reverse direction exercises both channels' send paths)
                await stream_b.write(payload)
                got_a = await _drain(stream_a, len(payload))
                assert got_a == payload, "B→A payload corrupted"

                await conn_a.close()
                await conn_b.close()
            finally:
                await bridge.stop()
                nursery.cancel_scope.cancel()

        nursery.start_soon(_run)
        # Bounded total runtime — ICE + DTLS + SCTP on localhost is typically
        # < 5s; 30s leaves headroom for slow CI without hanging indefinitely.
        with trio.move_on_after(30):
            await trio.sleep_forever()


@pytest.mark.trio
async def test_multiple_concurrent_streams() -> None:
    """
    Two streams on the same PC must not collide.  This exercises the
    inbound (odd) / outbound (even) id-space separation introduced with
    in-band channels.
    """
    async with trio.open_nursery() as nursery:
        bridge = AsyncioBridge()
        await bridge.start()

        async def _run() -> None:
            try:
                conn_a, conn_b, _cert_a, _cert_b = await _setup_loopback(bridge)
                stream_a1 = list(conn_a._streams.values())[0]
                stream_b1 = await conn_b.accept_stream()

                # Open a second stream on the same connection.
                stream_a2 = await conn_a.open_stream()
                stream_b2 = await conn_b.accept_stream()

                # Send distinct payloads on each — must not get cross-wired.
                await stream_a1.write(b"stream-one")
                await stream_a2.write(b"stream-two")
                assert (await _drain(stream_b1, len(b"stream-one"))) == b"stream-one"
                assert (await _drain(stream_b2, len(b"stream-two"))) == b"stream-two"

                await conn_a.close()
                await conn_b.close()
            finally:
                await bridge.stop()
                nursery.cancel_scope.cancel()

        nursery.start_soon(_run)
        with trio.move_on_after(30):
            await trio.sleep_forever()
