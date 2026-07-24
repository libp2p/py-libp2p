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
                await asyncio.sleep(0.05)  # give event loop time to deliver
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
