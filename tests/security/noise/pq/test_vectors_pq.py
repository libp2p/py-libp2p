"""
Cross-implementation test vectors for Noise_XXhfs_25519+XWing_ChaChaPoly_SHA256.

Loads the 5 committed vectors from js-libp2p-noise and reproduces each
handshake with the exact same fixed seeds. Asserts byte-exact equality of:
  - messages A, B, C
  - final handshake hash (ss.h after Message C)
  - transport cipher keys cs1.k and cs2.k

All 5 vectors passing proves the Python and JavaScript implementations are
wire-compatible.

Key seeding:
  - Initiator ephemeral DH   : ephemeral_dh_i_{public,private}
  - Responder ephemeral DH   : ephemeral_dh_r_{public,private}
  - Initiator KEM keypair    : ephemeral_kem_i_{public,secret}
  - Responder encap seed     : encap_seed_hex (64 bytes)
      [0:32]  = ML-KEM randomness m
      [32:64] = X25519 ephemeral private key

Prologue for all vectors: empty (ZEROLEN = b""), which the Noise spec requires
to be mixed even when empty: h = SHA256(SHA256(protocol_name)).
"""

import hashlib
import json
from pathlib import Path

import pytest
from nacl.bindings import crypto_scalarmult, crypto_scalarmult_base

from kyber_py.ml_kem import ML_KEM_768

from libp2p.security.noise.pq.kem import (
    _ML_KEM_PK_SIZE,
    _ML_KEM_CT_SIZE,
    _X25519_KEY_SIZE,
    _xwing_combine,
)
from libp2p.security.noise.pq.noise_state import SymmetricState, _hkdf

# ---------------------------------------------------------------------------
# Vector file location
# ---------------------------------------------------------------------------

_VECTORS_PATH = (
    Path(__file__).parents[4].parent  # PQC-Research/
    / "js-libp2p-noise"
    / "test"
    / "fixtures"
    / "pqc-test-vectors.json"
)

# Size constants (mirror patterns_pq.py)
_AEAD_TAG = 16
_KEM_CT_ENC_SIZE = _ML_KEM_CT_SIZE + _X25519_KEY_SIZE + _AEAD_TAG  # 1136
_S_ENC_SIZE = _X25519_KEY_SIZE + _AEAD_TAG                          # 48


# ---------------------------------------------------------------------------
# Seeded X-Wing encapsulate (for responder with fixed seed)
# ---------------------------------------------------------------------------


def _xwing_encapsulate_seeded(pk: bytes, encap_seed: bytes) -> tuple[bytes, bytes]:
    """
    Deterministic X-Wing encapsulation using a 64-byte seed.

    seed[0:32]  = ML-KEM randomness m (passed to _encaps_internal)
    seed[32:64] = X25519 ephemeral private key

    Matches XWing.encapsulate(pubkey, seed) from @noble/post-quantum.

    Returns:
        (ciphertext, shared_secret) — same layout as XWingKem.encapsulate()
    """
    assert len(pk) == _ML_KEM_PK_SIZE + _X25519_KEY_SIZE, f"bad pk len: {len(pk)}"
    assert len(encap_seed) == 64, f"seed must be 64 bytes, got {len(encap_seed)}"

    ml_kem_pk = pk[:_ML_KEM_PK_SIZE]
    x25519_pk_r = pk[_ML_KEM_PK_SIZE:]

    # ML-KEM with deterministic randomness
    m = encap_seed[:32]
    ss_mlkem, ml_kem_ct = ML_KEM_768._encaps_internal(ml_kem_pk, m)

    # X25519 with fixed ephemeral private key
    x25519_eph_sk = encap_seed[32:]
    x25519_eph_pk = bytes(crypto_scalarmult_base(x25519_eph_sk))
    ss_x25519 = bytes(crypto_scalarmult(x25519_eph_sk, x25519_pk_r))

    ss = _xwing_combine(ss_mlkem, ss_x25519, x25519_eph_pk, x25519_pk_r)
    ct = ml_kem_ct + x25519_eph_pk
    return ct, ss


# ---------------------------------------------------------------------------
# X-Wing seed expansion (matches @noble/post-quantum combineKEMS + expandSeedXof)
# ---------------------------------------------------------------------------


def _xwing_sk_from_seed(seed: bytes) -> bytes:
    """
    Expand a 32-byte X-Wing root seed into the full 2432-byte secret key.

    @noble/post-quantum stores secretKey as the 32-byte root seed and
    re-expands on each decapsulate call using:
        expanded = SHAKE-256(seed, 96 bytes)
        expanded[0:32]  = ML-KEM-768 d (randomness)
        expanded[32:64] = ML-KEM-768 z (implicit rejection randomness)
        expanded[64:96] = X25519 private key

    Returns:
        2432-byte X-Wing secret key (ml_kem_dk || x25519_sk)
    """
    assert len(seed) == 32, f"seed must be 32 bytes, got {len(seed)}"
    expanded = hashlib.shake_256(seed).digest(96)
    d = expanded[0:32]
    z = expanded[32:64]
    x25519_sk = expanded[64:96]
    _ml_kem_pk, ml_kem_sk = ML_KEM_768._keygen_internal(d, z)
    return ml_kem_sk + x25519_sk


# ---------------------------------------------------------------------------
# Deterministic handshake reproducer
# ---------------------------------------------------------------------------


def _run_vector_handshake(v: dict) -> dict:
    """
    Reproduce the XXhfs handshake with all keys fixed from a test vector.

    Returns:
        dict with keys: msg_a, msg_b, msg_c, handshake_hash, cs1_k, cs2_k
    """
    # Load fixed values
    e_i_sk = bytes.fromhex(v["ephemeral_dh_i_private"])
    e_i_pk = bytes.fromhex(v["ephemeral_dh_i_public"])
    e_r_sk = bytes.fromhex(v["ephemeral_dh_r_private"])
    e_r_pk = bytes.fromhex(v["ephemeral_dh_r_public"])
    static_i_sk = bytes.fromhex(v["static_i_private"])
    static_i_pk = bytes.fromhex(v["static_i_public"])
    static_r_sk = bytes.fromhex(v["static_r_private"])
    static_r_pk = bytes.fromhex(v["static_r_public"])
    e1_pk = bytes.fromhex(v["ephemeral_kem_i_public"])
    # ephemeral_kem_i_secret is a 32-byte root seed (not the full 2432-byte key)
    # @noble/post-quantum stores the root seed as secretKey and re-expands via SHAKE-256
    e1_sk = _xwing_sk_from_seed(bytes.fromhex(v["ephemeral_kem_i_secret"]))
    encap_seed = bytes.fromhex(v["encap_seed_hex"])
    # Prologue: ZEROLEN = b""

    # ---- Initiator SymmetricState ----------------------------------------
    ss_i = SymmetricState()
    ss_i.mix_hash(b"")  # MixHash(prologue=empty)

    # ---- Responder SymmetricState ----------------------------------------
    ss_r = SymmetricState()
    ss_r.mix_hash(b"")  # MixHash(prologue=empty)

    # ======================================================================
    # Message A: initiator sends  e_pk || e1_pk  (no payload, no AEAD yet)
    # ======================================================================
    ss_i.mix_hash(e_i_pk)    # writeE  token
    ss_i.mix_hash(e1_pk)     # writeE1 token  (encryptAndHash = mixHash when no key)
    enc_payload_a = ss_i.encrypt_and_hash(b"")   # empty payload → b""
    msg_a = e_i_pk + e1_pk + enc_payload_a       # 32 + 1216 + 0 = 1248 B

    # Responder processes Message A
    ss_r.mix_hash(e_i_pk)
    ss_r.mix_hash(e1_pk)
    ss_r.decrypt_and_hash(enc_payload_a)  # mix_hash(b"") — keeps states in sync

    # ======================================================================
    # Message B: responder sends  e_pk || enc_ct || enc_s || enc_payload
    # Tokens: e, ee, ekem1, s, es
    # ======================================================================
    ss_r.mix_hash(e_r_pk)                         # writeE

    dh_ee = bytes(crypto_scalarmult(e_r_sk, e_i_pk))
    ss_r.mix_key(dh_ee)                           # writeEE

    # writeEkem1: encapsulate, encrypt ct, then mix KEM ss
    ct, ss_kem_r = _xwing_encapsulate_seeded(e1_pk, encap_seed)
    enc_ct = ss_r.encrypt_and_hash(ct)            # encrypted under ee-derived key
    ss_r.mix_key(ss_kem_r)                        # then strengthen with KEM output

    # writeS: encrypt responder static pubkey
    enc_s_r = ss_r.encrypt_and_hash(static_r_pk)

    # writeES (responder role): MixKey(DH(s_responder, e_initiator))
    dh_es_r = bytes(crypto_scalarmult(static_r_sk, e_i_pk))
    ss_r.mix_key(dh_es_r)

    # payload = ZEROLEN
    enc_payload_b = ss_r.encrypt_and_hash(b"")
    msg_b = e_r_pk + enc_ct + enc_s_r + enc_payload_b  # 32+1136+48+16 = 1232 B

    # Initiator processes Message B
    ss_i.mix_hash(e_r_pk)

    dh_ee_i = bytes(crypto_scalarmult(e_i_sk, e_r_pk))
    ss_i.mix_key(dh_ee_i)                         # ee token

    # readEkem1: decrypt ct, then decapsulate, then mix KEM ss
    from libp2p.security.noise.pq.kem import XWingKem
    ct_dec = ss_i.decrypt_and_hash(enc_ct)
    ss_kem_i = XWingKem().decapsulate(ct_dec, e1_sk)
    ss_i.mix_key(ss_kem_i)

    # readS: decrypt responder static pubkey
    dec_s_r = ss_i.decrypt_and_hash(enc_s_r)

    # readES (initiator role): MixKey(DH(e_initiator, s_responder))
    dh_es_i = bytes(crypto_scalarmult(e_i_sk, dec_s_r))
    ss_i.mix_key(dh_es_i)

    ss_i.decrypt_and_hash(enc_payload_b)  # empty payload

    # ======================================================================
    # Message C: initiator sends  enc_s || enc_payload
    # Tokens: s, se
    # ======================================================================
    # writeS: encrypt initiator static pubkey
    enc_s_i = ss_i.encrypt_and_hash(static_i_pk)

    # writeSE (initiator role): MixKey(DH(s_initiator, e_responder))
    dh_se_i = bytes(crypto_scalarmult(static_i_sk, e_r_pk))
    ss_i.mix_key(dh_se_i)

    enc_payload_c = ss_i.encrypt_and_hash(b"")
    msg_c = enc_s_i + enc_payload_c  # 48 + 16 = 64 B

    # Responder processes Message C
    dec_s_i = ss_r.decrypt_and_hash(enc_s_i)

    # readSE (responder role): MixKey(DH(e_responder, s_initiator))
    dh_se_r = bytes(crypto_scalarmult(e_r_sk, dec_s_i))
    ss_r.mix_key(dh_se_r)

    ss_r.decrypt_and_hash(enc_payload_c)

    # ======================================================================
    # Split — both sides must derive the same cipher keys
    # ======================================================================
    cs1_k, cs2_k = _hkdf(ss_i.ck, b"", 2)
    cs1_k_r, cs2_k_r = _hkdf(ss_r.ck, b"", 2)
    assert cs1_k == cs1_k_r, "cs1 key mismatch between initiator and responder"
    assert cs2_k == cs2_k_r, "cs2 key mismatch between initiator and responder"

    return {
        "msg_a": msg_a,
        "msg_b": msg_b,
        "msg_c": msg_c,
        "handshake_hash": ss_i.h,
        "cs1_k": cs1_k,
        "cs2_k": cs2_k,
    }


# ---------------------------------------------------------------------------
# Test fixture loading
# ---------------------------------------------------------------------------


def _load_vectors() -> list[dict]:
    if not _VECTORS_PATH.exists():
        pytest.skip(f"JS test vectors not found at {_VECTORS_PATH}")
    with open(_VECTORS_PATH) as f:
        data = json.load(f)
    assert data["protocol"] == "Noise_XXhfs_25519+XWing_ChaChaPoly_SHA256"
    return data["vectors"]


# ---------------------------------------------------------------------------
# Parameterised tests
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def vectors() -> list[dict]:
    return _load_vectors()


class TestVectorsMeta:
    def test_protocol_name(self) -> None:
        if not _VECTORS_PATH.exists():
            pytest.skip("JS test vectors not found")
        with open(_VECTORS_PATH) as f:
            data = json.load(f)
        assert data["protocol"] == "Noise_XXhfs_25519+XWing_ChaChaPoly_SHA256"

    def test_five_vectors_present(self, vectors: list[dict]) -> None:
        assert len(vectors) == 5


class TestVectorHandshake:
    """One test class; vectors are parameterised inside each test method."""

    @pytest.mark.parametrize("idx", range(5))
    def test_msg_a_bytes(self, vectors: list[dict], idx: int) -> None:
        v = vectors[idx]
        result = _run_vector_handshake(v)
        assert len(result["msg_a"]) == v["msg_a_bytes"], (
            f"Vector {idx}: msg_a length {len(result['msg_a'])} != {v['msg_a_bytes']}"
        )

    @pytest.mark.parametrize("idx", range(5))
    def test_msg_a_content(self, vectors: list[dict], idx: int) -> None:
        v = vectors[idx]
        result = _run_vector_handshake(v)
        got = result["msg_a"].hex()
        assert got == v["msg_a"], (
            f"Vector {idx}: msg_a mismatch\n"
            f"  got:      {got[:64]}...\n"
            f"  expected: {v['msg_a'][:64]}..."
        )

    @pytest.mark.parametrize("idx", range(5))
    def test_msg_b_bytes(self, vectors: list[dict], idx: int) -> None:
        v = vectors[idx]
        result = _run_vector_handshake(v)
        assert len(result["msg_b"]) == v["msg_b_bytes"], (
            f"Vector {idx}: msg_b length {len(result['msg_b'])} != {v['msg_b_bytes']}"
        )

    @pytest.mark.parametrize("idx", range(5))
    def test_msg_b_content(self, vectors: list[dict], idx: int) -> None:
        v = vectors[idx]
        result = _run_vector_handshake(v)
        got = result["msg_b"].hex()
        assert got == v["msg_b"], (
            f"Vector {idx}: msg_b mismatch\n"
            f"  got:      {got[:64]}...\n"
            f"  expected: {v['msg_b'][:64]}..."
        )

    @pytest.mark.parametrize("idx", range(5))
    def test_msg_c_bytes(self, vectors: list[dict], idx: int) -> None:
        v = vectors[idx]
        result = _run_vector_handshake(v)
        assert len(result["msg_c"]) == v["msg_c_bytes"], (
            f"Vector {idx}: msg_c length {len(result['msg_c'])} != {v['msg_c_bytes']}"
        )

    @pytest.mark.parametrize("idx", range(5))
    def test_msg_c_content(self, vectors: list[dict], idx: int) -> None:
        v = vectors[idx]
        result = _run_vector_handshake(v)
        got = result["msg_c"].hex()
        assert got == v["msg_c"], (
            f"Vector {idx}: msg_c mismatch\n"
            f"  got:      {got[:64]}...\n"
            f"  expected: {v['msg_c'][:64]}..."
        )

    @pytest.mark.parametrize("idx", range(5))
    def test_handshake_hash(self, vectors: list[dict], idx: int) -> None:
        v = vectors[idx]
        result = _run_vector_handshake(v)
        got = result["handshake_hash"].hex()
        assert got == v["handshake_hash"], (
            f"Vector {idx}: handshake_hash mismatch — transcript diverged\n"
            f"  got:      {got}\n"
            f"  expected: {v['handshake_hash']}"
        )

    @pytest.mark.parametrize("idx", range(5))
    def test_cs1_k(self, vectors: list[dict], idx: int) -> None:
        v = vectors[idx]
        result = _run_vector_handshake(v)
        got = result["cs1_k"].hex()
        assert got == v["cs1_k"], (
            f"Vector {idx}: cs1_k mismatch\n"
            f"  got:      {got}\n"
            f"  expected: {v['cs1_k']}"
        )

    @pytest.mark.parametrize("idx", range(5))
    def test_cs2_k(self, vectors: list[dict], idx: int) -> None:
        v = vectors[idx]
        result = _run_vector_handshake(v)
        got = result["cs2_k"].hex()
        assert got == v["cs2_k"], (
            f"Vector {idx}: cs2_k mismatch\n"
            f"  got:      {got}\n"
            f"  expected: {v['cs2_k']}"
        )
