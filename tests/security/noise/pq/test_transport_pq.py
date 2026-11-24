"""
Tests for TransportPQ: the ISecureTransport wrapper for XXhfs.

Follows TDD: these tests are written before the implementation.
"""

import math

import pytest
from multiaddr import Multiaddr
import trio

from libp2p.abc import IRawConnection
from libp2p.connection_types import ConnectionType
from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.crypto.keys import KeyPair
from libp2p.crypto.x25519 import X25519PrivateKey
from libp2p.peer.id import ID
from libp2p.security.noise.pq.kem import IKem
from libp2p.security.noise.pq.transport_pq import PROTOCOL_ID, TransportPQ
from tests.security.noise.pq.helpers import KEM_BACKENDS, make_kem

# ---------------------------------------------------------------------------
# Shared in-memory connection helpers (mirrors test_patterns_pq.py)
# ---------------------------------------------------------------------------


class _MemoryConn(IRawConnection):
    is_initiator: bool = False

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

    def get_remote_address(self) -> tuple[str, int] | None:
        return None

    def get_transport_addresses(self) -> list[Multiaddr]:
        return []

    def get_connection_type(self) -> ConnectionType:
        return ConnectionType.UNKNOWN


def _make_conn_pair() -> tuple[_MemoryConn, _MemoryConn]:
    a_to_b_send, a_to_b_recv = trio.open_memory_channel(math.inf)
    b_to_a_send, b_to_a_recv = trio.open_memory_channel(math.inf)
    return (
        _MemoryConn(a_to_b_send, b_to_a_recv),
        _MemoryConn(b_to_a_send, a_to_b_recv),
    )


def _make_transport(kem: IKem | None = None) -> tuple[TransportPQ, ID]:
    kp = create_new_key_pair()
    noise_key = X25519PrivateKey.new()
    peer = ID.from_pubkey(kp.public_key)
    transport = TransportPQ(
        libp2p_keypair=KeyPair(kp.private_key, kp.public_key),
        noise_privkey=noise_key,
        kem=kem,
    )
    return transport, peer


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestTransportPQInit:
    def test_protocol_id(self) -> None:
        assert PROTOCOL_ID == "/noise-mlkem768-hfs/0.2.0"

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
        assert pattern.PROTOCOL_NAME == b"Noise_XXhfs_25519+MLKEM768_ChaChaPoly_SHA256"


@pytest.mark.parametrize("kem_backend", KEM_BACKENDS)
class TestTransportPQHandshake:
    """
    Full transport-level handshakes, run once per KEM backend.

    Both backends have to keep working end to end: make_fast_kem() picks
    the native one wherever it is available, so without this
    parametrisation kyber-py would have no handshake-level coverage at all
    on a machine where the native backend loads.
    """

    @pytest.mark.trio
    async def test_secure_inbound_and_outbound_complete(self, kem_backend: str) -> None:
        """secure_outbound + secure_inbound both return a SecureSession."""
        local_transport, local_peer = _make_transport(kem=make_kem(kem_backend))
        remote_transport, remote_peer = _make_transport(kem=make_kem(kem_backend))
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
    async def test_data_exchange_after_secure_transport(self, kem_backend: str) -> None:
        """Data written via secure_outbound is readable via secure_inbound."""
        local_transport, _ = _make_transport(kem=make_kem(kem_backend))
        remote_transport, remote_peer = _make_transport(kem=make_kem(kem_backend))
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
    async def test_peer_ids_correct_after_transport(self, kem_backend: str) -> None:
        """Both sides see the correct remote peer ID after the secure upgrade."""
        local_transport, local_peer = _make_transport(kem=make_kem(kem_backend))
        remote_transport, remote_peer = _make_transport(kem=make_kem(kem_backend))
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
    async def test_is_initiator_flag(self, kem_backend: str) -> None:
        """secure_outbound returns is_initiator=True, secure_inbound returns False."""
        local_transport, _ = _make_transport(kem=make_kem(kem_backend))
        remote_transport, remote_peer = _make_transport(kem=make_kem(kem_backend))
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


class TestTransportPQKemSelection:
    """The transport resolves its KEM once, and an explicit one is honoured."""

    def test_get_pattern_uses_an_explicitly_supplied_kem(self) -> None:
        kem = make_kem("kyber-py")
        transport, _ = _make_transport(kem=kem)
        assert transport.get_pattern().kem is kem

    def test_the_kem_is_resolved_once_not_per_connection(self) -> None:
        # get_pattern() runs on every inbound connection, before the peer has
        # authenticated anything. Selecting a backend there charged each
        # connection for a probe of cryptography's ML-KEM support.
        transport, _ = _make_transport()
        assert transport.get_pattern().kem is transport.get_pattern().kem

    def test_the_kem_is_resolved_at_construction(self) -> None:
        transport, _ = _make_transport()
        assert isinstance(transport.kem, IKem)

    def test_no_working_backend_fails_at_construction_not_on_first_connection(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A host with neither backend should refuse to be built, rather than
        # listen happily and fail the first peer that dials it.
        from libp2p.security.noise.pq import kem as kem_module
        from libp2p.security.noise.pq.kem_backends import _select_kem_class

        def _no_native() -> object:
            raise ImportError("simulated: cryptography has no mlkem module")

        def _no_kyber(self: object) -> None:
            raise ImportError("simulated: kyber-py is not installed")

        monkeypatch.setattr(kem_module, "_load_native_mlkem", _no_native)
        monkeypatch.setattr(kem_module.MLKEM768Kem, "__init__", _no_kyber)
        _select_kem_class.cache_clear()
        try:
            with pytest.raises(ImportError, match=r"libp2p\[pq\]"):
                _make_transport()
        finally:
            _select_kem_class.cache_clear()
