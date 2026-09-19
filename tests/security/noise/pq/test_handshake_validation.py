"""
Fail-closed parsing tests for the XXhfs handshake (security audit F-001/F-004).

Every handshake field is a fixed size on the wire, but a Python slice of a
short buffer silently yields a short result. These tests drive truncated,
oversized and zero-length messages A, B and C at both roles and require a
typed ``HandshakeMalformed`` every time, so no attacker-chosen slice can
reach ``crypto_scalarmult``, the KEM or ``decrypt_and_hash``.

The message-C case is the sharp one: the length there is chosen *after* a
successful AEAD decryption, so it is attacker-controlled even though the
peer is inside the encrypted part of the handshake.
"""

from collections.abc import Callable
import os

import pytest
from nacl.bindings import crypto_scalarmult, crypto_scalarmult_base
import nacl.utils
import trio

from libp2p.abc import IRawConnection, ISecureConn
from libp2p.security.noise.exceptions import HandshakeMalformed
from libp2p.security.noise.pq.kem import MLKEM768_CT_SIZE, MLKEM768_PK_SIZE
from libp2p.security.noise.pq.kem_backends import make_fast_kem
from libp2p.security.noise.pq.noise_state import SymmetricState
from tests.security.noise.pq.helpers import (
    make_conn_pair,
    make_pattern,
    read_frame,
    write_frame,
)

_X25519_SIZE = 32
_AEAD_TAG = 16
_KEM_CT_ENC_SIZE = MLKEM768_CT_SIZE + _AEAD_TAG  # 1104
_S_ENC_SIZE = _X25519_SIZE + _AEAD_TAG  # 48

_MSG_A_MIN = _X25519_SIZE + MLKEM768_PK_SIZE  # 1216
_MSG_B_MIN = _X25519_SIZE + _KEM_CT_ENC_SIZE + _S_ENC_SIZE  # 1184
_MSG_C_MIN = _S_ENC_SIZE  # 48

# Anything past this much trailing payload is refused outright.
_PAYLOAD_CEILING = 4096


# ---------------------------------------------------------------------------
# Message A: responder side, fully pre-authentication
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "size",
    [
        pytest.param(0, id="empty"),
        pytest.param(1, id="one-byte"),
        pytest.param(4, id="four-bytes-the-reported-case"),
        pytest.param(_X25519_SIZE - 1, id="short-e"),
        pytest.param(_X25519_SIZE, id="e-only-no-e1"),
        pytest.param(_MSG_A_MIN - 1, id="one-byte-short"),
        pytest.param(_MSG_A_MIN + _PAYLOAD_CEILING + 1, id="oversized"),
    ],
)
@pytest.mark.trio
async def test_responder_rejects_malformed_message_a(size: int) -> None:
    resp_pat, _, _, _ = make_pattern()
    attacker_conn, resp_conn = make_conn_pair()

    # The connection pair is backed by unbounded channels, so the hostile
    # frame can simply be queued up front instead of racing in a nursery.
    await write_frame(attacker_conn, os.urandom(size))

    with pytest.raises(HandshakeMalformed):
        await resp_pat.handshake_inbound(resp_conn)


# ---------------------------------------------------------------------------
# Message B: initiator side
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "size",
    [
        pytest.param(0, id="empty"),
        pytest.param(1, id="one-byte"),
        pytest.param(_X25519_SIZE - 1, id="short-e"),
        pytest.param(_X25519_SIZE + 1, id="e-plus-one"),
        pytest.param(_MSG_B_MIN - 1, id="one-byte-short"),
        pytest.param(_MSG_B_MIN + _PAYLOAD_CEILING + 1, id="oversized"),
    ],
)
@pytest.mark.trio
async def test_initiator_rejects_malformed_message_b(size: int) -> None:
    init_pat, _, _, _ = make_pattern()
    _, _, _, some_peer = make_pattern()
    init_conn, attacker_conn = make_conn_pair()

    # Queue the hostile message B before the handshake starts; the initiator
    # writes its own message A into an unbounded channel and reads this next.
    await write_frame(attacker_conn, os.urandom(size))

    with pytest.raises(HandshakeMalformed):
        await init_pat.handshake_outbound(init_conn, some_peer)


# ---------------------------------------------------------------------------
# Message C: responder side, after a genuine A and B
# ---------------------------------------------------------------------------


class _ScriptedInitiator:
    """
    A minimal initiator that runs messages A and B honestly and then emits
    whatever message C the test asks for.

    It mirrors ``PatternXXhfs.handshake_outbound`` up to the point where
    message C is written, which is what makes the message-C cases reachable:
    by then it shares the handshake key with the responder, so it can produce
    AEAD ciphertexts the responder will accept.
    """

    def __init__(self, conn: IRawConnection) -> None:
        self._conn = conn
        self._kem = make_fast_kem()
        self.ss = SymmetricState()

    async def run_a_and_b(self) -> None:
        ss = self.ss
        ss.mix_hash(b"")

        e_sk = nacl.utils.random(_X25519_SIZE)
        e_pk = bytes(crypto_scalarmult_base(e_sk))
        ss.mix_hash(e_pk)
        e1_pk, e1_sk = self._kem.keygen()
        ss.mix_hash(e1_pk)
        await write_frame(self._conn, e_pk + e1_pk + ss.encrypt_and_hash(b""))

        msg_b = await read_frame(self._conn)
        offset = 0
        resp_e_pk = msg_b[offset : offset + _X25519_SIZE]
        offset += _X25519_SIZE
        ss.mix_hash(resp_e_pk)
        ss.mix_key(bytes(crypto_scalarmult(e_sk, resp_e_pk)))

        enc_ct = msg_b[offset : offset + _KEM_CT_ENC_SIZE]
        offset += _KEM_CT_ENC_SIZE
        ss.mix_key(self._kem.decapsulate(ss.decrypt_and_hash(enc_ct), e1_sk))

        enc_s = msg_b[offset : offset + _S_ENC_SIZE]
        offset += _S_ENC_SIZE
        resp_s_pk_bytes = ss.decrypt_and_hash(enc_s)
        ss.mix_key(bytes(crypto_scalarmult(e_sk, resp_s_pk_bytes)))
        ss.decrypt_and_hash(msg_b[offset:])

    async def send_raw_message_c(self, body: bytes) -> None:
        await write_frame(self._conn, body)


async def _assert_message_c_rejected(
    make_msg_c: Callable[["_ScriptedInitiator"], bytes],
) -> None:
    """
    Run a real responder against a scripted initiator that sends a hostile
    message C, and require a typed ``HandshakeMalformed``.

    ``pytest.raises`` sits inside the nursery body so the responder's error is
    caught where it is raised, rather than being repackaged as an
    ``ExceptionGroup`` on nursery exit.
    """
    resp_pat, _, _, _ = make_pattern()
    attacker_conn, resp_conn = make_conn_pair()
    attacker = _ScriptedInitiator(attacker_conn)

    async with trio.open_nursery() as nursery:

        async def attack() -> None:
            await attacker.run_a_and_b()
            await attacker.send_raw_message_c(make_msg_c(attacker))

        nursery.start_soon(attack)
        with pytest.raises(HandshakeMalformed):
            await resp_pat.handshake_inbound(resp_conn)


@pytest.mark.parametrize(
    "size",
    [
        pytest.param(0, id="empty"),
        pytest.param(1, id="one-byte"),
        pytest.param(20, id="twenty-bytes"),
        pytest.param(_MSG_C_MIN - 1, id="one-byte-short"),
        pytest.param(_MSG_C_MIN + _PAYLOAD_CEILING + 1, id="oversized"),
    ],
)
@pytest.mark.trio
async def test_responder_rejects_malformed_message_c(size: int) -> None:
    await _assert_message_c_rejected(lambda _a: os.urandom(size))


@pytest.mark.trio
async def test_responder_rejects_short_static_key_in_message_c() -> None:
    """
    Audit F-001, the post-AEAD variant.

    The attacker completes A and B honestly, so it holds the handshake key and
    can forge a *valid* 20-byte ciphertext whose plaintext is only 4 bytes.
    Before the fix the responder sliced ``msg_c[0:48]``, got the whole 20-byte
    frame, decrypted it successfully and handed a 4-byte "public key" to
    ``crypto_scalarmult``, which reads 32 bytes regardless.
    """

    def short_s(attacker: _ScriptedInitiator) -> bytes:
        body = attacker.ss.encrypt_and_hash(b"AAAA")
        assert len(body) == 4 + _AEAD_TAG == 20
        return body

    await _assert_message_c_rejected(short_s)


# ---------------------------------------------------------------------------
# All-zero X25519 output (audit F-005)
# ---------------------------------------------------------------------------


@pytest.mark.trio
async def test_responder_rejects_all_zero_dh_output() -> None:
    """
    An all-zero X25519 shared secret must fail closed with a typed error.

    PyNaCl already refuses the degenerate result, but it raises
    ``nacl.exceptions.RuntimeError``, which is not part of any documented
    py-libp2p contract. This pins both halves: the handshake is rejected, and
    it is rejected as a ``HandshakeMalformed``.
    """
    resp_pat, _, _, _ = make_pattern()
    attacker_conn, resp_conn = make_conn_pair()
    e1_pk, _ = make_fast_kem().keygen()
    low_order_e = b"\x00" * _X25519_SIZE
    await write_frame(attacker_conn, low_order_e + e1_pk)

    with pytest.raises(HandshakeMalformed):
        await resp_pat.handshake_inbound(resp_conn)


# ---------------------------------------------------------------------------
# The happy path still works
# ---------------------------------------------------------------------------


@pytest.mark.trio
async def test_valid_handshake_still_succeeds() -> None:
    """Validation must not break a well-formed handshake."""
    init_pat, _, _, _ = make_pattern()
    resp_pat, _, _, resp_peer = make_pattern()
    init_conn, resp_conn = make_conn_pair()

    sessions: list[ISecureConn | None] = [None, None]

    async def run_init() -> None:
        sessions[0] = await init_pat.handshake_outbound(init_conn, resp_peer)

    async def run_resp() -> None:
        sessions[1] = await resp_pat.handshake_inbound(resp_conn)

    async with trio.open_nursery() as nursery:
        nursery.start_soon(run_init)
        nursery.start_soon(run_resp)

    assert sessions[0] is not None
    assert sessions[1] is not None
    assert sessions[0].get_remote_peer() == resp_peer
