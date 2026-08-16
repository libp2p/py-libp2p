"""
Tests for libp2p.transport.webrtc._udp_mux.UdpMux.

All tests are sync wrappers so they run outside trio_mode and don't
interfere with the project-wide trio backend.

Coverage:
  - STUN datagram is dispatched to the registered protocol by ufrag
  - STUN with unknown ufrag is silently dropped (no crash)
  - Non-STUN datagram is dispatched by remote addr (post-ICE path)
  - Non-STUN from unknown addr is silently dropped
  - _MuxedTransport.close() resolves protocol's __closed future
  - add_ice_connection() registers the connection and sets up the candidate
"""

from __future__ import annotations

import asyncio
import struct
from unittest.mock import patch

import pytest

try:
    import aioice.stun as _stun

    from libp2p.transport.webrtc._udp_mux import UdpMux, _MuxedTransport

    HAS_AIOICE = True
except ImportError:
    HAS_AIOICE = False

pytestmark = pytest.mark.skipif(not HAS_AIOICE, reason="aioice not installed")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stun_binding_request(username: str) -> bytes:
    """Craft a minimal STUN BINDING REQUEST with the given USERNAME."""
    msg = _stun.Message(
        message_method=_stun.Method.BINDING,
        message_class=_stun.Class.REQUEST,
    )
    msg.attributes["USERNAME"] = username
    return bytes(msg)


def _dtls_like_bytes() -> bytes:
    """Return bytes that look like DTLS (non-STUN) — TLS record header."""
    # DTLS 1.2 record: content_type=22 (handshake), version=0xfeff, ...
    return b"\x16\xfe\xff\x00\x01\x00\x00\x00\x00\x00\x00\x00\x05hello"


class _RecordingReceiver:
    """Stand-in for aioice.ice.Connection's data path."""

    def __init__(self) -> None:
        self.data: list[tuple[bytes, int]] = []

    def data_received(self, data: bytes, component: int) -> None:
        self.data.append((data, component))


class _RecordingProtocol:
    """Stand-in for aioice.ice.StunProtocol — records what it receives."""

    def __init__(self) -> None:
        self.received: list[tuple[bytes, tuple[str, int]]] = []

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        self.received.append((data, addr))

    def connection_lost(self, exc: object) -> None:
        pass


# ---------------------------------------------------------------------------
# STUN dispatch
# ---------------------------------------------------------------------------


class TestStunDispatch:
    def test_known_ufrag_dispatches_to_protocol(self) -> None:
        asyncio.run(self._known_ufrag())

    async def _known_ufrag(self) -> None:
        mux, port = await UdpMux.create("127.0.0.1", 0)
        proto = _RecordingProtocol()
        mux.register("abc123", proto)
        try:
            data = _stun_binding_request("abc123:remote456")
            mux.datagram_received(data, ("10.0.0.1", 12345))
            assert len(proto.received) == 1
            assert proto.received[0][1] == ("10.0.0.1", 12345)
        finally:
            await mux.close()

    def test_unknown_ufrag_is_dropped_silently(self) -> None:
        asyncio.run(self._unknown_ufrag())

    async def _unknown_ufrag(self) -> None:
        mux, _ = await UdpMux.create("127.0.0.1", 0)
        proto = _RecordingProtocol()
        mux.register("abc123", proto)
        try:
            data = _stun_binding_request("different:remote")
            mux.datagram_received(data, ("10.0.0.1", 12345))
            assert proto.received == []
        finally:
            await mux.close()

    def test_unknown_ufrag_invokes_handler(self) -> None:
        asyncio.run(self._unknown_ufrag_handler())

    async def _unknown_ufrag_handler(self) -> None:
        mux, _ = await UdpMux.create("127.0.0.1", 0)
        seen: list[tuple[str, bytes, tuple[str, int]]] = []
        mux.set_unknown_stun_handler(
            lambda ufrag, data, addr: seen.append((ufrag, data, addr))
        )
        try:
            data = _stun_binding_request("newdialer:remote")
            mux.datagram_received(data, ("10.0.0.9", 5555))
            # First contact for an unregistered ufrag reaches the handler with
            # the ufrag, raw datagram (for replay), and source address.
            assert seen == [("newdialer", data, ("10.0.0.9", 5555))]
        finally:
            await mux.close()

    def test_unregister_stops_dispatch(self) -> None:
        asyncio.run(self._unregister())

    async def _unregister(self) -> None:
        mux, _ = await UdpMux.create("127.0.0.1", 0)
        proto = _RecordingProtocol()
        mux.register("abc123", proto)
        mux.unregister("abc123")
        try:
            data = _stun_binding_request("abc123:remote456")
            mux.datagram_received(data, ("10.0.0.1", 12345))
            assert proto.received == []
        finally:
            await mux.close()


# ---------------------------------------------------------------------------
# Addr dispatch (post-ICE non-STUN)
# ---------------------------------------------------------------------------


class TestAddrDispatch:
    def test_known_addr_dispatches_to_protocol(self) -> None:
        asyncio.run(self._known_addr())

    async def _known_addr(self) -> None:
        mux, _ = await UdpMux.create("127.0.0.1", 0)
        proto = _RecordingProtocol()
        remote = ("10.0.0.2", 54321)
        mux.register_addr(remote, proto)
        try:
            data = _dtls_like_bytes()
            mux.datagram_received(data, remote)
            assert len(proto.received) == 1
            assert proto.received[0][0] == data
        finally:
            await mux.close()

    def test_unknown_addr_is_dropped_silently(self) -> None:
        asyncio.run(self._unknown_addr())

    async def _unknown_addr(self) -> None:
        mux, _ = await UdpMux.create("127.0.0.1", 0)
        proto = _RecordingProtocol()
        mux.register_addr(("10.0.0.2", 54321), proto)
        try:
            data = _dtls_like_bytes()
            mux.datagram_received(data, ("10.0.0.3", 9999))
            assert proto.received == []
        finally:
            await mux.close()

    def test_unregister_addr_stops_dispatch(self) -> None:
        asyncio.run(self._unregister_addr())

    async def _unregister_addr(self) -> None:
        mux, _ = await UdpMux.create("127.0.0.1", 0)
        proto = _RecordingProtocol()
        remote = ("10.0.0.2", 54321)
        mux.register_addr(remote, proto)
        mux.unregister_addr(remote)
        try:
            data = _dtls_like_bytes()
            mux.datagram_received(data, remote)
            assert proto.received == []
        finally:
            await mux.close()


# ---------------------------------------------------------------------------
# Malformed STUN
# ---------------------------------------------------------------------------


class TestAddrLearning:
    def test_stun_for_known_ufrag_learns_remote_addr(self) -> None:
        asyncio.run(self._learns())

    async def _learns(self) -> None:
        mux, _ = await UdpMux.create("127.0.0.1", 0)
        proto = _RecordingProtocol()
        remote = ("10.0.0.9", 40000)
        mux.register("abc123", proto)
        try:
            req = _stun_binding_request("abc123:peer")  # random txn id per call
            mux.datagram_received(req, remote)
            # A DTLS record from the same address now routes without an
            # explicit register_addr().
            mux.datagram_received(_dtls_like_bytes(), remote)
            assert [d for d, _ in proto.received] == [req, _dtls_like_bytes()]
        finally:
            await mux.close()

    def test_learned_addrs_are_capped_per_protocol(self) -> None:
        asyncio.run(self._capped())

    async def _capped(self) -> None:
        mux, _ = await UdpMux.create("127.0.0.1", 0)
        proto = _RecordingProtocol()
        mux.register("abc123", proto)
        try:
            cap = UdpMux._MAX_ADDRS_PER_PROTOCOL
            for port in range(40000, 40000 + cap + 20):
                mux.datagram_received(
                    _stun_binding_request("abc123:peer"), ("10.0.0.9", port)
                )
            learned = [a for a, p in mux._by_addr.items() if p is proto]
            assert len(learned) == cap
            # STUN with the known ufrag still reaches the protocol regardless.
            assert len(proto.received) == cap + 20
        finally:
            await mux.close()

    def test_newer_connection_takes_over_reused_addr(self) -> None:
        asyncio.run(self._takeover())

    async def _takeover(self) -> None:
        # A dialer that redials from the same (ip, port) with a new ufrag
        # while the old connection is still registered must reach the new one.
        mux, _ = await UdpMux.create("127.0.0.1", 0)
        old, new = _RecordingProtocol(), _RecordingProtocol()
        remote = ("10.0.0.9", 40000)
        mux.register("oldufrag", old)
        mux.register("newufrag", new)
        try:
            mux.datagram_received(_stun_binding_request("oldufrag:x"), remote)
            mux.datagram_received(_stun_binding_request("newufrag:x"), remote)
            mux.datagram_received(_dtls_like_bytes(), remote)
            assert [d for d, _ in new.received][-1] == _dtls_like_bytes()
            assert all(d != _dtls_like_bytes() for d, _ in old.received)
            mux.unregister("newufrag")
            assert remote not in mux._by_addr
        finally:
            await mux.close()

    def test_unregister_drops_learned_addrs(self) -> None:
        asyncio.run(self._unregister_drops())

    async def _unregister_drops(self) -> None:
        mux, _ = await UdpMux.create("127.0.0.1", 0)
        proto, other = _RecordingProtocol(), _RecordingProtocol()
        remote, other_remote = ("10.0.0.9", 40000), ("10.0.0.10", 40001)
        mux.register("abc123", proto)
        mux.register_addr(other_remote, other)
        try:
            mux.datagram_received(_stun_binding_request("abc123:peer"), remote)
            mux.unregister("abc123")
            assert mux._by_ufrag == {}
            assert mux._by_addr == {other_remote: other}  # unrelated entry kept
            mux.datagram_received(_dtls_like_bytes(), remote)
            assert len(proto.received) == 1  # nothing after unregister
        finally:
            await mux.close()


class TestMalformedStun:
    def test_struct_error_routes_by_addr_not_raise(self) -> None:
        asyncio.run(self._struct_error())

    async def _struct_error(self) -> None:
        # aioice parses STUN attributes with struct.unpack, which raises
        # struct.error (NOT a ValueError subclass) on a malformed/short
        # fixed-width attribute. datagram_received must treat that as "not
        # usable STUN" and fall through to addr routing instead of letting the
        # exception escape — otherwise a remote peer can crash / log-flood the
        # mux with crafted packets.
        # aioice's own StunProtocol.datagram_received re-parses and catches
        # only ValueError, so the bytes must NOT go through it either — they
        # are handed straight to the connection's data path (``receiver``).
        mux, _ = await UdpMux.create("127.0.0.1", 0)
        proto = _RecordingProtocol()
        proto.receiver = _RecordingReceiver()  # type: ignore[attr-defined]
        remote = ("10.0.0.2", 54321)
        mux.register_addr(remote, proto)
        try:
            data = b"\x00\x01" + b"\x00" * 26  # STUN-shaped bytes
            with patch.object(
                _stun, "parse_message", side_effect=struct.error("bad attr")
            ):
                # Must not raise.
                mux.datagram_received(data, remote)
            assert proto.received == []  # StunProtocol parser bypassed
            assert proto.receiver.data == [(data, 1)]  # type: ignore[attr-defined]
        finally:
            await mux.close()

    def test_struct_error_without_receiver_is_dropped(self) -> None:
        asyncio.run(self._struct_error_no_receiver())

    async def _struct_error_no_receiver(self) -> None:
        mux, _ = await UdpMux.create("127.0.0.1", 0)
        proto = _RecordingProtocol()  # no .receiver attribute
        remote = ("10.0.0.2", 54321)
        mux.register_addr(remote, proto)
        try:
            with patch.object(
                _stun, "parse_message", side_effect=struct.error("bad attr")
            ):
                mux.datagram_received(b"\x00\x01" + b"\x00" * 26, remote)
            assert proto.received == []
        finally:
            await mux.close()


# ---------------------------------------------------------------------------
# _MuxedTransport
# ---------------------------------------------------------------------------


class TestMuxedTransport:
    def test_sendto_delegates_to_real_transport(self) -> None:
        asyncio.run(self._sendto())

    async def _sendto(self) -> None:
        mux, mux_port = await UdpMux.create("127.0.0.1", 0)
        try:
            # Open a real UDP socket to receive what the mux sends.
            loop = asyncio.get_event_loop()
            received: list[bytes] = []

            class _Echo(asyncio.DatagramProtocol):
                def datagram_received(self, data, addr):
                    received.append(data)

            server_transport, _ = await loop.create_datagram_endpoint(
                _Echo, local_addr=("127.0.0.1", 0)
            )
            server_addr = server_transport.get_extra_info("sockname")[:2]
            try:
                mt = _MuxedTransport(mux._transport, mux.local_addr)
                mt.sendto(b"hello", server_addr)
                # Poll until delivered instead of a fixed sleep (flakes on load).
                for _ in range(200):
                    if received:
                        break
                    await asyncio.sleep(0.01)
                assert received == [b"hello"]
            finally:
                server_transport.close()
        finally:
            await mux.close()

    def test_get_extra_info_sockname(self) -> None:
        asyncio.run(self._sockname())

    async def _sockname(self) -> None:
        mux, port = await UdpMux.create("127.0.0.1", 0)
        try:
            mt = _MuxedTransport(mux._transport, mux.local_addr)
            assert mt.get_extra_info("sockname") == ("127.0.0.1", port)
            assert mt.get_extra_info("unknown") is None
        finally:
            await mux.close()

    def test_close_calls_connection_lost_on_protocol(self) -> None:
        asyncio.run(self._close())

    async def _close(self) -> None:
        mux, _ = await UdpMux.create("127.0.0.1", 0)
        try:
            proto = _RecordingProtocol()
            mt = _MuxedTransport(mux._transport, mux.local_addr)
            mt._protocol = proto
            connection_lost_called = []
            proto.connection_lost = lambda exc: connection_lost_called.append(exc)
            mt.close()
            assert connection_lost_called == [None]
        finally:
            await mux.close()


# ---------------------------------------------------------------------------
# add_ice_connection
# ---------------------------------------------------------------------------


class TestAddIceConnection:
    def test_connection_is_registered_and_has_candidate(self) -> None:
        asyncio.run(self._add_conn())

    async def _add_conn(self) -> None:
        mux, port = await UdpMux.create("127.0.0.1", 0)
        # RFC 5245: ufrag >= 4 chars, password >= 22 chars
        ufrag = "myufrag1"
        password = "mypassword1234567890ab"
        try:
            conn = mux.add_ice_connection(ufrag, password, host="127.0.0.1")
            # Registered for STUN dispatch
            assert ufrag in mux._by_ufrag
            # Has one protocol with a local candidate pointing at the mux port
            assert len(conn._protocols) == 1
            cand = conn._protocols[0].local_candidate
            assert cand is not None
            assert cand.port == port
            assert cand.host == "127.0.0.1"
            assert cand.transport == "udp"
            # local_username / local_password set correctly
            assert conn.local_username == ufrag
            assert conn.local_password == password
        finally:
            await mux.close()

    def test_connect_reachable_without_extra_binds(self) -> None:
        asyncio.run(self._connect_reachable())

    async def _connect_reachable(self) -> None:
        mux, _ = await UdpMux.create("127.0.0.1", 0)
        ufrag = "cxn1"
        password = "cxnpassword1234567890ab"
        try:
            conn = mux.add_ice_connection(ufrag, password, host="127.0.0.1")
            # The fix: gathering is marked complete and the host candidate is
            # exposed, so connect() clears the "Local candidates gathering was
            # not performed" guard. A real gather would have appended extra
            # protocols (each binding its own UDP socket); we have exactly one.
            assert conn._local_candidates_end is True
            assert conn._local_candidates == [conn._protocols[0].local_candidate]
            assert len(conn._protocols) == 1

            # Drive connect() to prove it gets past the gather guard: with remote
            # creds set and end-of-candidates, it fails on ICE negotiation (no
            # real peer) — NOT on skipped gathering.
            conn.remote_username = "remoteuf1"
            conn.remote_password = "remotepassword1234567890"
            await conn.add_remote_candidate(None)
            with pytest.raises(ConnectionError) as exc:
                await asyncio.wait_for(conn.connect(), timeout=5.0)
            assert "gathering" not in str(exc.value).lower()
        finally:
            await mux.close()

    def test_stun_for_connection_dispatches_to_its_protocol(self) -> None:
        asyncio.run(self._stun_for_conn())

    async def _stun_for_conn(self) -> None:
        mux, _ = await UdpMux.create("127.0.0.1", 0)
        # RFC 5245: ufrag >= 4 chars, password >= 22 chars
        ufrag = "uf1x"
        password = "pw1password1234567890ab"
        try:
            # Register the connection so the ufrag is in the dispatch table,
            # then replace it with a recorder to observe dispatch without
            # triggering real aioice connectivity checks.
            mux.add_ice_connection(ufrag, password, host="127.0.0.1")
            recorder = _RecordingProtocol()
            mux._by_ufrag[ufrag] = recorder

            data = _stun_binding_request(f"{ufrag}:remote_uf")
            mux.datagram_received(data, ("192.168.1.1", 9000))
            assert len(recorder.received) == 1
        finally:
            await mux.close()


# ---------------------------------------------------------------------------
# attach_muxed_connection: full aiortc PC over the mux
# ---------------------------------------------------------------------------


class TestAttachMuxedConnection:
    def test_pc_over_mux_connects_and_routes(self) -> None:
        asyncio.run(asyncio.wait_for(self._pc_over_mux(), timeout=30))

    async def _pc_over_mux(self) -> None:
        # Bind the mux on all interfaces and advertise a real host address:
        # the client PC gathers LAN host candidates only (aioice skips
        # loopback), and on Windows a 127.0.0.1-bound socket cannot send to a
        # LAN-bound peer socket (WinError 1231) - Linux's weak-host model hid
        # this. Mirrors a real listener on 0.0.0.0.
        from aioice.ice import get_host_addresses
        from aiortc import RTCSessionDescription

        from libp2p.transport.webrtc._aiortc_helpers import (
            _wait_channel_open,
            attach_muxed_connection,
            create_noise_channel,
            create_peer_connection,
            wait_for_connected,
        )
        from libp2p.transport.webrtc.certificate import WebRTCCertificate

        hosts = get_host_addresses(use_ipv4=True, use_ipv6=False) or ["127.0.0.1"]
        cand_host = hosts[0]
        mux, port = await UdpMux.create("0.0.0.0", 0)
        ufrag, pwd = "srvufrag1", "srvpassword1234567890ab"
        cert_s, cert_c = (
            WebRTCCertificate.from_aiortc(),
            WebRTCCertificate.from_aiortc(),
        )
        pc_s = pc_c = None
        try:
            conn = mux.add_ice_connection(ufrag, pwd, host=cand_host)
            pc_s = await create_peer_connection(cert_s._rtc_certificate, ice_servers=[])
            ch_s = await create_noise_channel(pc_s)
            attach_muxed_connection(pc_s, mux, conn)

            pc_c = await create_peer_connection(cert_c._rtc_certificate, ice_servers=[])
            ch_c = await create_noise_channel(pc_c)

            offer = await pc_c.createOffer()
            await pc_c.setLocalDescription(offer)
            # Force the muxed side to be the DTLS server (WebRTC-Direct
            # listeners must be): with actpass aiortc answers as DTLS client.
            offer_sdp = pc_c.localDescription.sdp.replace(
                "a=setup:actpass", "a=setup:active"
            )
            await pc_s.setRemoteDescription(
                RTCSessionDescription(sdp=offer_sdp, type="offer")
            )
            answer = await pc_s.createAnswer()
            await pc_s.setLocalDescription(answer)
            answer_sdp = pc_s.localDescription.sdp
            await pc_c.setRemoteDescription(
                RTCSessionDescription(sdp=answer_sdp, type="answer")
            )

            # The answer advertises exactly the shared port and our creds —
            # aiortc's gather() did not bind/append any extra sockets.
            cands = [
                ln for ln in answer_sdp.splitlines() if ln.startswith("a=candidate")
            ]
            assert len(cands) == 1 and f" {port} " in cands[0], cands
            assert f"a=ice-ufrag:{ufrag}" in answer_sdp
            assert f"a=ice-pwd:{pwd}" in answer_sdp
            assert "a=setup:passive" in answer_sdp
            assert len(conn._protocols) == 1

            await asyncio.gather(
                wait_for_connected(pc_s, timeout=15.0),
                wait_for_connected(pc_c, timeout=15.0),
            )

            # Data flows both ways over the shared socket.
            await asyncio.gather(_wait_channel_open(ch_s), _wait_channel_open(ch_c))
            got_s: asyncio.Queue[bytes] = asyncio.Queue()
            got_c: asyncio.Queue[bytes] = asyncio.Queue()
            ch_s.on("message", lambda m: got_s.put_nowait(m))
            ch_c.on("message", lambda m: got_c.put_nowait(m))
            ch_c.send(b"client->server")
            assert await asyncio.wait_for(got_s.get(), 5) == b"client->server"
            ch_s.send(b"server->client")
            assert await asyncio.wait_for(got_c.get(), 5) == b"server->client"

            # Peer address learned/registered for post-ICE routing.
            assert ufrag in mux._by_ufrag
            assert conn._nominated[1].remote_addr in mux._by_addr

            await pc_c.close()
            await pc_s.close()
            pc_s = pc_c = None
            # closing the ICE transport unregisters everything for this ufrag
            assert mux._by_ufrag == {}
            assert mux._by_addr == {}
        finally:
            for pc in (pc_s, pc_c):
                if pc is not None:
                    await pc.close()
            await mux.close()
