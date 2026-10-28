"""
Tests for PatternXXhfs: the Noise XXhfs handshake with ML-KEM-768.

Follows TDD: these tests are written before the implementation and initially fail.
"""

import pytest
import trio

from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.crypto.x25519 import X25519PrivateKey
from libp2p.peer.id import ID
from libp2p.security.noise.exceptions import (
    PeerIDMismatchesPubkey,
)
from libp2p.security.noise.pq.patterns_pq import PatternXXhfs
from tests.security.noise.pq.helpers import (
    KEM_BACKENDS,
    NATIVE_KEM,
    NATIVE_KEM_SKIP_REASON,
    PURE_KEM,
    WriteCapture as _WriteCapture,
    make_conn_pair as _make_conn_pair,
    make_kem as _make_kem,
    make_pattern as _make_pattern,
)

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
        assert pattern.PROTOCOL_NAME == b"Noise_XXhfs_25519+MLKEM768_ChaChaPoly_SHA256"

    def test_default_kem_is_mlkem768(self) -> None:
        # Either backend is acceptable here; make_fast_kem() picks the native
        # one when available and kyber-py otherwise. What the pattern needs is
        # an ML-KEM-768 KEM with the right wire sizes.
        from libp2p.security.noise.pq.kem import IKem, MLKEM768Kem, MLKEM768NativeKem

        pattern, _, _, _ = _make_pattern()
        assert isinstance(pattern.kem, IKem)
        assert isinstance(pattern.kem, MLKEM768Kem | MLKEM768NativeKem)
        pk, _sk = pattern.kem.keygen()
        assert len(pk) == 1184


@pytest.mark.parametrize("kem_backend", KEM_BACKENDS)
class TestPatternXXhfsHandshake:
    """
    Full-handshake integration tests, run once per KEM backend.

    make_fast_kem() picks the native backend wherever it is available, so
    without this parametrisation every end-to-end test here would resolve
    to the same backend and kyber-py would keep only unit-level coverage.
    """

    @pytest.mark.trio
    async def test_handshake_completes(self, kem_backend: str) -> None:
        """Both sides return a SecureSession after the handshake."""
        init_pat, _, _, _ = _make_pattern(kem=_make_kem(kem_backend))
        resp_pat, _, _, resp_peer = _make_pattern(kem=_make_kem(kem_backend))
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
    async def test_bidirectional_data_exchange(self, kem_backend: str) -> None:
        """Data written by each side is received correctly by the other."""
        init_pat, _, _, _ = _make_pattern(kem=_make_kem(kem_backend))
        resp_pat, _, _, resp_peer = _make_pattern(kem=_make_kem(kem_backend))
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
    async def test_peer_ids_are_correct(self, kem_backend: str) -> None:
        """Both sides see the correct remote peer ID after the handshake."""
        init_pat, _, _, init_peer = _make_pattern(kem=_make_kem(kem_backend))
        resp_pat, _, _, resp_peer = _make_pattern(kem=_make_kem(kem_backend))
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
    async def test_peer_id_mismatch_raises(self, kem_backend: str) -> None:
        """Initiator raises PeerIDMismatchesPubkey when peer ID is wrong."""
        init_pat, _, _, _ = _make_pattern(kem=_make_kem(kem_backend))
        resp_pat, _, _, resp_peer = _make_pattern(kem=_make_kem(kem_backend))
        _, _, _, wrong_peer = _make_pattern(kem=_make_kem(kem_backend))
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
    async def test_large_payload_exchange(self, kem_backend: str) -> None:
        """Transport handles payloads larger than a single cipher block."""
        init_pat, _, _, _ = _make_pattern(kem=_make_kem(kem_backend))
        resp_pat, _, _, resp_peer = _make_pattern(kem=_make_kem(kem_backend))
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
    async def test_independent_sessions_dont_interfere(self, kem_backend: str) -> None:
        """Two simultaneous handshakes produce independent, non-interfering sessions."""
        ip1, _, _, _ = _make_pattern(kem=_make_kem(kem_backend))
        rp1, _, _, rp1_peer = _make_pattern(kem=_make_kem(kem_backend))
        ip2, _, _, _ = _make_pattern(kem=_make_kem(kem_backend))
        rp2, _, _, rp2_peer = _make_pattern(kem=_make_kem(kem_backend))

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


@pytest.mark.parametrize("kem_backend", KEM_BACKENDS)
class TestPatternXXhfsWireFormat:
    """
    Verify the on-wire message layout.

    Run on both backends: the wire encoding of ML-KEM-768 is what the two
    have to agree on, so a size that differed between them would break
    interoperability rather than just local performance.
    """

    @pytest.mark.trio
    async def test_message_a_is_1216_bytes(self, kem_backend: str) -> None:
        """Message A = e_pk(32) + e1_pk(1184) = 1216 bytes payload."""
        init_pat, _, _, _ = _make_pattern(kem=_make_kem(kem_backend))
        resp_pat, _, _, resp_peer = _make_pattern(kem=_make_kem(kem_backend))

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
        assert msg_len == 1216, f"Expected 1216, got {msg_len}"

    @pytest.mark.trio
    async def test_message_b_overhead(self, kem_backend: str) -> None:
        """Message B = e(32) + enc_ct(1104) + enc_s(48) + enc_payload(len+16)."""
        init_pat, _, _, _ = _make_pattern(kem=_make_kem(kem_backend))
        resp_pat, _, _, resp_peer = _make_pattern(kem=_make_kem(kem_backend))

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

        # Fixed overhead: 32 (e) + 1104 (enc_ct) + 48 (enc_s) + 16 (AEAD tag)
        # Payload size varies (protobuf-serialised NoiseHandshakePayload) but
        # total fixed overhead is constant
        fixed_overhead = 32 + 1104 + 48 + 16
        assert msg_len >= fixed_overhead, (
            f"Message B too short: {msg_len} < {fixed_overhead}"
        )


class TestKemInjection:
    """The pattern uses the KEM it is handed, not a freshly selected one."""

    def test_make_pattern_honours_an_explicit_kem(self) -> None:
        from tests.security.noise.pq.helpers import make_kem

        kem = make_kem("kyber-py")
        pattern, _, _, _ = _make_pattern(kem=kem)
        assert pattern.kem is kem


@pytest.mark.skipif(
    NATIVE_KEM_SKIP_REASON is not None,
    reason=NATIVE_KEM_SKIP_REASON or "",
)
class TestMixedBackendHandshake:
    """
    A handshake between peers on *different* ML-KEM-768 backends.

    This is the property the interop story rests on: only the encapsulation
    key and the ciphertext cross the wire, and those are identical between
    kyber-py and the native backend, so a peer on either must complete a
    handshake with a peer on the other. Every other end-to-end test here runs
    both sides on the same backend, which cannot catch a divergence in the
    wire encoding.
    """

    @staticmethod
    async def _handshake(init_kem_name: str, resp_kem_name: str) -> None:
        init_kem = _make_kem(init_kem_name)
        resp_kem = _make_kem(resp_kem_name)
        assert type(init_kem) is not type(resp_kem), (
            "this test is meaningless unless the two sides really differ"
        )

        init_pat, _, _, init_peer = _make_pattern(kem=init_kem)
        resp_pat, _, _, resp_peer = _make_pattern(kem=resp_kem)
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
        assert init_sess is not None and resp_sess is not None
        assert init_sess.remote_peer == resp_peer
        assert resp_sess.remote_peer == init_peer

        # The transport keys only agree if both sides derived the same KEM
        # shared secret, so a round trip in each direction is the real
        # assertion that the two backends interoperated.
        await init_sess.write(b"native-meets-pure")
        assert await resp_sess.read(len(b"native-meets-pure")) == b"native-meets-pure"
        await resp_sess.write(b"pure-meets-native")
        assert await init_sess.read(len(b"pure-meets-native")) == b"pure-meets-native"

    @pytest.mark.trio
    async def test_native_initiator_against_pure_python_responder(self) -> None:
        await self._handshake(NATIVE_KEM, PURE_KEM)

    @pytest.mark.trio
    async def test_pure_python_initiator_against_native_responder(self) -> None:
        await self._handshake(PURE_KEM, NATIVE_KEM)
