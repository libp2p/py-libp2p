"""
Tests for PatternXXhfs: the Noise XXhfs handshake with X-Wing KEM.

Follows TDD: these tests are written before the implementation and initially fail.
"""

import math

import pytest
import trio

from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.crypto.x25519 import X25519PrivateKey
from libp2p.peer.id import ID
from libp2p.security.noise.exceptions import (
    PeerIDMismatchesPubkey,
)
from libp2p.security.noise.pq.patterns_pq import PatternXXhfs

# ---------------------------------------------------------------------------
# In-memory connection helpers
# ---------------------------------------------------------------------------


class _MemoryConn:
    """
    Async in-memory bidirectional stream backed by trio memory channels.

    Implements the ReadWriteCloser duck-type expected by NoisePacketReadWriter.
    """

    def __init__(self, send_chan, recv_chan) -> None:
        self._send = send_chan
        self._recv = recv_chan
        self._buf = bytearray()

    async def read(self, n: int | None = None) -> bytes:
        while not self._buf:
            try:
                chunk = await self._recv.receive()
            except trio.EndOfChannel:
                return b""
            self._buf.extend(chunk)
        if n is None:
            data = bytes(self._buf)
            self._buf.clear()
            return data
        data = bytes(self._buf[:n])
        del self._buf[:n]
        return data

    async def write(self, data: bytes) -> None:
        await self._send.send(bytes(data))

    async def close(self) -> None:
        await self._send.aclose()

    def get_remote_address(self) -> None:
        return None

    def get_transport_addresses(self) -> list:
        return []

    def get_connection_type(self):
        from libp2p.connection_types import ConnectionType

        return ConnectionType.UNKNOWN


class _WriteCapture:
    """Wraps a connection and records every call to write()."""

    def __init__(self, inner: _MemoryConn) -> None:
        self._inner = inner
        self.writes: list[bytes] = []

    async def read(self, n: int | None = None) -> bytes:
        return await self._inner.read(n)

    async def write(self, data: bytes) -> None:
        self.writes.append(bytes(data))
        await self._inner.write(data)

    async def close(self) -> None:
        await self._inner.close()

    def get_remote_address(self) -> None:
        return None

    def get_transport_addresses(self) -> list:
        return []

    def get_connection_type(self):
        from libp2p.connection_types import ConnectionType

        return ConnectionType.UNKNOWN


def _make_conn_pair() -> tuple[_MemoryConn, _MemoryConn]:
    """Create a pair of in-memory connections wired together."""
    a_to_b_send, a_to_b_recv = trio.open_memory_channel(math.inf)
    b_to_a_send, b_to_a_recv = trio.open_memory_channel(math.inf)
    init_conn = _MemoryConn(a_to_b_send, b_to_a_recv)
    resp_conn = _MemoryConn(b_to_a_send, a_to_b_recv)
    return init_conn, resp_conn


def _make_pattern() -> tuple[PatternXXhfs, object, object, ID]:
    """Create a fresh PatternXXhfs with newly-generated keys."""
    kp = create_new_key_pair()
    noise_key = X25519PrivateKey.new()
    peer = ID.from_pubkey(kp.public_key)
    pattern = PatternXXhfs(
        local_peer=peer,
        libp2p_privkey=kp.private_key,
        noise_static_key=noise_key,
    )
    return pattern, kp, noise_key, peer


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPatternXXhfsInit:
    """Basic construction and attribute checks."""

    def test_instantiation_stores_fields(self) -> None:
        kp = create_new_key_pair()
        noise_key = X25519PrivateKey.new()
        peer = ID.from_pubkey(kp.public_key)
        pattern = PatternXXhfs(
            local_peer=peer,
            libp2p_privkey=kp.private_key,
            noise_static_key=noise_key,
        )
        assert pattern.local_peer is peer
        assert pattern.libp2p_privkey is kp.private_key
        assert pattern.noise_static_key is noise_key
        assert pattern.early_data is None

    def test_protocol_name(self) -> None:
        pattern, _, _, _ = _make_pattern()
        assert pattern.PROTOCOL_NAME == b"Noise_XXhfs_25519+XWing_ChaChaPoly_SHA256"

    def test_default_kem_is_xwing(self) -> None:
        from libp2p.security.noise.pq.kem import XWingKem

        pattern, _, _, _ = _make_pattern()
        assert isinstance(pattern.kem, XWingKem)


class TestPatternXXhfsHandshake:
    """Full-handshake integration tests."""

    @pytest.mark.trio
    async def test_handshake_completes(self) -> None:
        """Both sides return a SecureSession after the handshake."""
        init_pat, _, _, _ = _make_pattern()
        resp_pat, _, _, resp_peer = _make_pattern()
        init_conn, resp_conn = _make_conn_pair()

        sessions: list = [None, None]

        async def run_init() -> None:
            sessions[0] = await init_pat.handshake_outbound(init_conn, resp_peer)

        async def run_resp() -> None:
            sessions[1] = await resp_pat.handshake_inbound(resp_conn)

        async with trio.open_nursery() as nursery:
            nursery.start_soon(run_init)
            nursery.start_soon(run_resp)

        assert sessions[0] is not None
        assert sessions[1] is not None

    @pytest.mark.trio
    async def test_bidirectional_data_exchange(self) -> None:
        """Data written by each side is received correctly by the other."""
        init_pat, _, _, _ = _make_pattern()
        resp_pat, _, _, resp_peer = _make_pattern()
        init_conn, resp_conn = _make_conn_pair()

        sessions: list = [None, None]

        async def run_init() -> None:
            sessions[0] = await init_pat.handshake_outbound(init_conn, resp_peer)

        async def run_resp() -> None:
            sessions[1] = await resp_pat.handshake_inbound(resp_conn)

        async with trio.open_nursery() as nursery:
            nursery.start_soon(run_init)
            nursery.start_soon(run_resp)

        init_sess, resp_sess = sessions

        # Initiator → Responder
        msg_i = b"hello from initiator"
        await init_sess.write(msg_i)
        assert await resp_sess.read(len(msg_i)) == msg_i

        # Responder → Initiator
        msg_r = b"hello from responder"
        await resp_sess.write(msg_r)
        assert await init_sess.read(len(msg_r)) == msg_r

    @pytest.mark.trio
    async def test_peer_ids_are_correct(self) -> None:
        """Both sides see the correct remote peer ID after the handshake."""
        init_pat, _, _, init_peer = _make_pattern()
        resp_pat, _, _, resp_peer = _make_pattern()
        init_conn, resp_conn = _make_conn_pair()

        sessions: list = [None, None]

        async def run_init() -> None:
            sessions[0] = await init_pat.handshake_outbound(init_conn, resp_peer)

        async def run_resp() -> None:
            sessions[1] = await resp_pat.handshake_inbound(resp_conn)

        async with trio.open_nursery() as nursery:
            nursery.start_soon(run_init)
            nursery.start_soon(run_resp)

        init_sess, resp_sess = sessions
        assert init_sess.remote_peer == resp_peer
        assert resp_sess.remote_peer == init_peer

    @pytest.mark.trio
    async def test_peer_id_mismatch_raises(self) -> None:
        """Initiator raises PeerIDMismatchesPubkey when peer ID is wrong."""
        init_pat, _, _, _ = _make_pattern()
        resp_pat, _, _, resp_peer = _make_pattern()
        _, _, _, wrong_peer = _make_pattern()
        init_conn, resp_conn = _make_conn_pair()

        init_error: Exception | None = None

        async def run_init() -> None:
            nonlocal init_error
            try:
                await init_pat.handshake_outbound(init_conn, wrong_peer)
            except PeerIDMismatchesPubkey as e:
                init_error = e
            except Exception:
                pass
            finally:
                # Closing the send side unblocks the responder waiting for Msg C.
                await init_conn.close()

        async def run_resp() -> None:
            try:
                await resp_pat.handshake_inbound(resp_conn)
            except Exception:
                pass

        async with trio.open_nursery() as nursery:
            nursery.start_soon(run_init)
            nursery.start_soon(run_resp)

        assert isinstance(init_error, PeerIDMismatchesPubkey)

    @pytest.mark.trio
    async def test_large_payload_exchange(self) -> None:
        """Transport handles payloads larger than a single cipher block."""
        init_pat, _, _, _ = _make_pattern()
        resp_pat, _, _, resp_peer = _make_pattern()
        init_conn, resp_conn = _make_conn_pair()

        sessions: list = [None, None]

        async def run_init() -> None:
            sessions[0] = await init_pat.handshake_outbound(init_conn, resp_peer)

        async def run_resp() -> None:
            sessions[1] = await resp_pat.handshake_inbound(resp_conn)

        async with trio.open_nursery() as nursery:
            nursery.start_soon(run_init)
            nursery.start_soon(run_resp)

        large_msg = b"Z" * 8192
        await sessions[0].write(large_msg)
        received = await sessions[1].read(8192)
        assert received == large_msg

    @pytest.mark.trio
    async def test_independent_sessions_dont_interfere(self) -> None:
        """Two simultaneous handshakes produce independent, non-interfering sessions."""
        ip1, _, _, _ = _make_pattern()
        rp1, _, _, rp1_peer = _make_pattern()
        ip2, _, _, _ = _make_pattern()
        rp2, _, _, rp2_peer = _make_pattern()

        ic1, rc1 = _make_conn_pair()
        ic2, rc2 = _make_conn_pair()

        sessions: list = [None] * 4

        async def h1_init() -> None:
            sessions[0] = await ip1.handshake_outbound(ic1, rp1_peer)

        async def h1_resp() -> None:
            sessions[1] = await rp1.handshake_inbound(rc1)

        async def h2_init() -> None:
            sessions[2] = await ip2.handshake_outbound(ic2, rp2_peer)

        async def h2_resp() -> None:
            sessions[3] = await rp2.handshake_inbound(rc2)

        async with trio.open_nursery() as nursery:
            nursery.start_soon(h1_init)
            nursery.start_soon(h1_resp)
            nursery.start_soon(h2_init)
            nursery.start_soon(h2_resp)

        assert all(s is not None for s in sessions)

        # Both pairs exchange data independently
        await sessions[0].write(b"pair1")
        await sessions[2].write(b"pair2")
        assert await sessions[1].read(5) == b"pair1"
        assert await sessions[3].read(5) == b"pair2"


class TestPatternXXhfsWireFormat:
    """Verify the on-wire message layout."""

    @pytest.mark.trio
    async def test_message_a_is_1248_bytes(self) -> None:
        """Message A = e_pk(32) + e1_pk(1216) = 1248 bytes payload."""
        init_pat, _, _, _ = _make_pattern()
        resp_pat, _, _, resp_peer = _make_pattern()

        inner_conn, resp_conn = _make_conn_pair()
        spy = _WriteCapture(inner_conn)

        sessions: list = [None, None]

        async def run_init() -> None:
            sessions[0] = await init_pat.handshake_outbound(spy, resp_peer)

        async def run_resp() -> None:
            sessions[1] = await resp_pat.handshake_inbound(resp_conn)

        async with trio.open_nursery() as nursery:
            nursery.start_soon(run_init)
            nursery.start_soon(run_resp)

        # spy.writes[0] = 2-byte length prefix + message A bytes
        assert len(spy.writes) >= 1
        frame = spy.writes[0]
        msg_len = int.from_bytes(frame[:2], "big")
        assert msg_len == 1248, f"Expected 1248, got {msg_len}"

    @pytest.mark.trio
    async def test_message_b_overhead(self) -> None:
        """Message B = e(32) + enc_ct(1136) + enc_s(48) + enc_payload(len+16)."""
        init_pat, _, _, _ = _make_pattern()
        resp_pat, _, _, resp_peer = _make_pattern()

        init_conn, inner_resp_conn = _make_conn_pair()
        spy = _WriteCapture(inner_resp_conn)

        sessions: list = [None, None]

        async def run_init() -> None:
            sessions[0] = await init_pat.handshake_outbound(init_conn, resp_peer)

        async def run_resp() -> None:
            sessions[1] = await resp_pat.handshake_inbound(spy)

        async with trio.open_nursery() as nursery:
            nursery.start_soon(run_init)
            nursery.start_soon(run_resp)

        # spy.writes[0] = framed message B
        assert len(spy.writes) >= 1
        frame = spy.writes[0]
        msg_len = int.from_bytes(frame[:2], "big")

        # Fixed overhead: 32 (e) + 1136 (enc_ct) + 48 (enc_s) + 16 (AEAD tag)
        # Payload size varies (protobuf-serialised NoiseHandshakePayload) but
        # total fixed overhead is constant
        fixed_overhead = 32 + 1136 + 48 + 16
        assert msg_len >= fixed_overhead, (
            f"Message B too short: {msg_len} < {fixed_overhead}"
        )
