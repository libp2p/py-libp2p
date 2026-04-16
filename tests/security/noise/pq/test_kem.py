"""Tests for the IKem interface and XWingKem implementation."""

import pytest

from libp2p.security.noise.pq.kem import XWingKem


class TestXWingKemKeySizes:
    """Verify X-Wing key and ciphertext sizes match the spec."""

    def setup_method(self) -> None:
        self.kem = XWingKem()

    def test_keygen_public_key_size(self) -> None:
        pk, _ = self.kem.keygen()
        # ML-KEM-768 ek (1184) + X25519 pk (32) = 1216
        assert len(pk) == 1216

    def test_keygen_secret_key_size(self) -> None:
        _, sk = self.kem.keygen()
        # ML-KEM-768 dk (2400) + X25519 sk (32) = 2432
        assert len(sk) == 2432

    def test_encapsulate_ciphertext_size(self) -> None:
        pk, _ = self.kem.keygen()
        ct, _ = self.kem.encapsulate(pk)
        # ML-KEM-768 ct (1088) + X25519 ephemeral pk (32) = 1120
        assert len(ct) == 1120

    def test_encapsulate_shared_secret_size(self) -> None:
        pk, _ = self.kem.keygen()
        _, ss = self.kem.encapsulate(pk)
        assert len(ss) == 32

    def test_decapsulate_shared_secret_size(self) -> None:
        pk, sk = self.kem.keygen()
        ct, _ = self.kem.encapsulate(pk)
        ss = self.kem.decapsulate(ct, sk)
        assert len(ss) == 32


class TestXWingKemRoundTrip:
    """Verify encapsulate and decapsulate produce the same shared secret."""

    def setup_method(self) -> None:
        self.kem = XWingKem()

    def test_round_trip(self) -> None:
        pk, sk = self.kem.keygen()
        ct, ss_enc = self.kem.encapsulate(pk)
        ss_dec = self.kem.decapsulate(ct, sk)
        assert ss_enc == ss_dec

    def test_round_trip_produces_32_byte_secret(self) -> None:
        pk, sk = self.kem.keygen()
        ct, ss_enc = self.kem.encapsulate(pk)
        ss_dec = self.kem.decapsulate(ct, sk)
        assert len(ss_enc) == 32
        assert len(ss_dec) == 32

    def test_different_keys_produce_different_secrets(self) -> None:
        pk1, sk1 = self.kem.keygen()
        pk2, sk2 = self.kem.keygen()
        ct1, ss1 = self.kem.encapsulate(pk1)
        ct2, ss2 = self.kem.encapsulate(pk2)
        assert ss1 != ss2

    def test_wrong_secret_key_produces_different_secret(self) -> None:
        pk, sk = self.kem.keygen()
        _, wrong_sk = self.kem.keygen()
        ct, ss_enc = self.kem.encapsulate(pk)
        ss_wrong = self.kem.decapsulate(ct, wrong_sk)
        assert ss_enc != ss_wrong


class TestXWingKemCombiner:
    """Verify the X-Wing combiner produces deterministic output."""

    def setup_method(self) -> None:
        self.kem = XWingKem()

    def test_same_inputs_produce_same_output(self) -> None:
        pk, sk = self.kem.keygen()
        ct, ss1 = self.kem.encapsulate(pk)
        # Encapsulate is non-deterministic (uses fresh ephemeral each time)
        # but decapsulate must be deterministic
        ss_dec1 = self.kem.decapsulate(ct, sk)
        ss_dec2 = self.kem.decapsulate(ct, sk)
        assert ss_dec1 == ss_dec2

    def test_encapsulate_is_non_deterministic(self) -> None:
        pk, _ = self.kem.keygen()
        ct1, _ = self.kem.encapsulate(pk)
        ct2, _ = self.kem.encapsulate(pk)
        # Different ephemeral X25519 keys each time
        assert ct1 != ct2
