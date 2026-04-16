"""Tests for the Noise CipherState and SymmetricState."""

import hashlib
import hmac
import struct

import pytest

from libp2p.security.noise.pq.noise_state import (
    PROTOCOL_NAME,
    CipherState,
    SymmetricState,
)


class TestCipherState:
    """Tests for CipherState (ChaCha20-Poly1305 with nonce counter)."""

    def test_encrypt_decrypt_round_trip(self) -> None:
        key = bytes(range(32))
        cs = CipherState(key)
        plaintext = b"hello noise"
        ad = b"associated data"
        ct = cs.encrypt_with_ad(ad, plaintext)
        cs2 = CipherState(key)
        result = cs2.decrypt_with_ad(ad, ct)
        assert result == plaintext

    def test_nonce_increments_on_encrypt(self) -> None:
        key = bytes(range(32))
        cs = CipherState(key)
        assert cs.n == 0
        cs.encrypt_with_ad(b"", b"msg1")
        assert cs.n == 1
        cs.encrypt_with_ad(b"", b"msg2")
        assert cs.n == 2

    def test_nonce_increments_on_decrypt(self) -> None:
        key = bytes(range(32))
        cs_enc = CipherState(key)
        cs_dec = CipherState(key)
        ct1 = cs_enc.encrypt_with_ad(b"", b"msg1")
        ct2 = cs_enc.encrypt_with_ad(b"", b"msg2")
        cs_dec.decrypt_with_ad(b"", ct1)
        assert cs_dec.n == 1
        cs_dec.decrypt_with_ad(b"", ct2)
        assert cs_dec.n == 2

    def test_wrong_ad_fails_decryption(self) -> None:
        key = bytes(range(32))
        cs_enc = CipherState(key)
        ct = cs_enc.encrypt_with_ad(b"correct ad", b"msg")
        cs_dec = CipherState(key)
        with pytest.raises(Exception):
            cs_dec.decrypt_with_ad(b"wrong ad", ct)

    def test_empty_plaintext(self) -> None:
        key = bytes(range(32))
        cs = CipherState(key)
        ct = cs.encrypt_with_ad(b"ad", b"")
        cs2 = CipherState(key)
        result = cs2.decrypt_with_ad(b"ad", ct)
        assert result == b""

    def test_ciphertext_is_longer_than_plaintext(self) -> None:
        """AEAD tag adds 16 bytes."""
        key = bytes(range(32))
        cs = CipherState(key)
        plaintext = b"hello"
        ct = cs.encrypt_with_ad(b"", plaintext)
        assert len(ct) == len(plaintext) + 16


class TestSymmetricState:
    """Tests for SymmetricState (HKDF, MixKey, MixHash, EncryptAndHash)."""

    def test_initial_hash_is_protocol_name_hash(self) -> None:
        ss = SymmetricState()
        # h = SHA256(PROTOCOL_NAME) since len(PROTOCOL_NAME) > 32
        expected_h = hashlib.sha256(PROTOCOL_NAME).digest()
        assert ss.h == expected_h

    def test_initial_chaining_key_equals_h(self) -> None:
        ss = SymmetricState()
        assert ss.ck == ss.h

    def test_mix_hash_updates_h(self) -> None:
        ss = SymmetricState()
        old_h = ss.h
        ss.mix_hash(b"some data")
        assert ss.h != old_h
        # h = SHA256(h || data)
        expected_h = hashlib.sha256(old_h + b"some data").digest()
        assert ss.h == expected_h

    def test_mix_key_updates_ck(self) -> None:
        ss = SymmetricState()
        old_ck = ss.ck
        ss.mix_key(b"shared secret" + bytes(19))  # 32 bytes
        assert ss.ck != old_ck

    def test_encrypt_and_hash_round_trip(self) -> None:
        ss_enc = SymmetricState()
        ss_dec = SymmetricState()

        # Give both states a key via mix_key
        ikm = bytes(32)
        ss_enc.mix_key(ikm)
        ss_dec.mix_key(ikm)

        plaintext = b"handshake payload"
        ct = ss_enc.encrypt_and_hash(plaintext)
        result = ss_dec.decrypt_and_hash(ct)
        assert result == plaintext

    def test_encrypt_and_hash_updates_h(self) -> None:
        ss = SymmetricState()
        ss.mix_key(bytes(32))
        old_h = ss.h
        ss.encrypt_and_hash(b"payload")
        assert ss.h != old_h

    def test_split_returns_two_cipher_states(self) -> None:
        ss = SymmetricState()
        ss.mix_key(bytes(32))
        c1, c2 = ss.split()
        # Both should be usable cipher states
        ct = c1.encrypt_with_ad(b"", b"msg")
        assert len(ct) > 0
        result = c2.encrypt_with_ad(b"", b"msg")
        assert len(result) > 0

    def test_split_produces_different_keys(self) -> None:
        ss = SymmetricState()
        ss.mix_key(bytes(32))
        c1, c2 = ss.split()
        # Encrypting same data with different keys gives different results
        ct1 = c1.encrypt_with_ad(b"", b"test")
        ct2 = c2.encrypt_with_ad(b"", b"test")
        assert ct1 != ct2

    def test_identical_states_split_identically(self) -> None:
        """Two symmetric states with the same transcript split to the same keys."""
        ikm = bytes(range(32))
        ss1 = SymmetricState()
        ss2 = SymmetricState()
        ss1.mix_hash(b"ephemeral key")
        ss2.mix_hash(b"ephemeral key")
        ss1.mix_key(ikm)
        ss2.mix_key(ikm)

        c1_init, c1_resp = ss1.split()
        c2_init, c2_resp = ss2.split()

        # Same input → same output
        assert c1_init.encrypt_with_ad(b"", b"msg") == c2_init.encrypt_with_ad(b"", b"msg")
