"""Tests for TransportPQ: the ISecureTransport wrapper for XXhfs.

Follows TDD: these tests are written before the implementation.
"""

import math

import pytest
import trio

from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.crypto.keys import KeyPair
from libp2p.crypto.x25519 import X25519PrivateKey
from libp2p.peer.id import ID
from libp2p.security.noise.pq.transport_pq import PROTOCOL_ID, TransportPQ


# ---------------------------------------------------------------------------
# Shared in-memory connection helpers (mirrors test_patterns_pq.py)
# ---------------------------------------------------------------------------


class _MemoryConn:
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


def _make_conn_pair() -> tuple[_MemoryConn, _MemoryConn]:
    a_to_b_send, a_to_b_recv = trio.open_memory_channel(math.inf)
    b_to_a_send, b_to_a_recv = trio.open_memory_channel(math.inf)
    return (
        _MemoryConn(a_to_b_send, b_to_a_recv),
        _MemoryConn(b_to_a_send, a_to_b_recv),
    )


def _make_transport() -> tuple[TransportPQ, ID]:
    kp = create_new_key_pair()
    noise_key = X25519PrivateKey.new()
    peer = ID.from_pubkey(kp.public_key)
    transport = TransportPQ(
        libp2p_keypair=KeyPair(kp.private_key, kp.public_key),
        noise_privkey=noise_key,
    )
    return transport, peer


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestTransportPQInit:
    def test_protocol_id(self) -> None:
        assert PROTOCOL_ID == "/noise-pq/1.0.0"

    def test_instantiation(self) -> None:
        transport, peer = _make_transport()
        assert transport.local_peer == peer

    def test_get_pattern_returns_xxhfs(self) -> None:
        from libp2p.security.noise.pq.patterns_pq import PatternXXhfs

        transport, _ = _make_transport()
        pattern = transport.get_pattern()
        assert isinstance(pattern, PatternXXhfs)

    def test_get_pattern_protocol_name(self) -> None:
        transport, _ = _make_transport()
        pattern = transport.get_pattern()
        assert pattern.PROTOCOL_NAME == b"Noise_XXhfs_25519+XWing_ChaChaPoly_SHA256"


class TestTransportPQHandshake:
    @pytest.mark.trio
    async def test_secure_inbound_and_outbound_complete(self) -> None:
        """secure_outbound + secure_inbound both return a SecureSession."""
        local_transport, local_peer = _make_transport()
        remote_transport, remote_peer = _make_transport()
        local_conn, remote_conn = _make_conn_pair()

        sessions: list = [None, None]

        async def do_outbound() -> None:
            sessions[0] = await local_transport.secure_outbound(local_conn, remote_peer)

        async def do_inbound() -> None:
            sessions[1] = await remote_transport.secure_inbound(remote_conn)

        async with trio.open_nursery() as nursery:
            nursery.start_soon(do_outbound)
            nursery.start_soon(do_inbound)

        assert sessions[0] is not None
        assert sessions[1] is not None

    @pytest.mark.trio
    async def test_data_exchange_after_secure_transport(self) -> None:
        """Data written via secure_outbound is readable via secure_inbound."""
        local_transport, _ = _make_transport()
        remote_transport, remote_peer = _make_transport()
        local_conn, remote_conn = _make_conn_pair()

        sessions: list = [None, None]

        async def do_outbound() -> None:
            sessions[0] = await local_transport.secure_outbound(local_conn, remote_peer)

        async def do_inbound() -> None:
            sessions[1] = await remote_transport.secure_inbound(remote_conn)

        async with trio.open_nursery() as nursery:
            nursery.start_soon(do_outbound)
            nursery.start_soon(do_inbound)

        outbound_sess, inbound_sess = sessions

        msg = b"post-quantum hello"
        await outbound_sess.write(msg)
        assert await inbound_sess.read(len(msg)) == msg

        reply = b"pq reply"
        await inbound_sess.write(reply)
        assert await outbound_sess.read(len(reply)) == reply

    @pytest.mark.trio
    async def test_peer_ids_correct_after_transport(self) -> None:
        """Both sides see the correct remote peer ID after the secure upgrade."""
        local_transport, local_peer = _make_transport()
        remote_transport, remote_peer = _make_transport()
        local_conn, remote_conn = _make_conn_pair()

        sessions: list = [None, None]

        async def do_outbound() -> None:
            sessions[0] = await local_transport.secure_outbound(local_conn, remote_peer)

        async def do_inbound() -> None:
            sessions[1] = await remote_transport.secure_inbound(remote_conn)

        async with trio.open_nursery() as nursery:
            nursery.start_soon(do_outbound)
            nursery.start_soon(do_inbound)

        outbound_sess, inbound_sess = sessions
        assert outbound_sess.remote_peer == remote_peer
        assert inbound_sess.remote_peer == local_peer

    @pytest.mark.trio
    async def test_is_initiator_flag(self) -> None:
        """secure_outbound returns is_initiator=True, secure_inbound returns False."""
        local_transport, _ = _make_transport()
        remote_transport, remote_peer = _make_transport()
        local_conn, remote_conn = _make_conn_pair()

        sessions: list = [None, None]

        async def do_outbound() -> None:
            sessions[0] = await local_transport.secure_outbound(local_conn, remote_peer)

        async def do_inbound() -> None:
            sessions[1] = await remote_transport.secure_inbound(remote_conn)

        async with trio.open_nursery() as nursery:
            nursery.start_soon(do_outbound)
            nursery.start_soon(do_inbound)

        assert sessions[0].is_initiator is True
        assert sessions[1].is_initiator is False
