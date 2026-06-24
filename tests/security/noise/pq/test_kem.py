"""Tests for the IKem interface and MLKEM768Kem implementation."""

from libp2p.security.noise.pq.kem import MLKEM768Kem


class TestMLKEM768KemKeySizes:
    """Verify ML-KEM-768 key and ciphertext sizes match the spec."""

    kem: MLKEM768Kem

    def setup_method(self) -> None:
        self.kem = MLKEM768Kem()

    def test_keygen_public_key_size(self) -> None:
        pk, _ = self.kem.keygen()
        # ML-KEM-768 encapsulation key = 1184 bytes
        assert len(pk) == 1184

    def test_keygen_secret_key_size(self) -> None:
        _, sk = self.kem.keygen()
        # ML-KEM-768 decapsulation key = 2400 bytes
        assert len(sk) == 2400

    def test_encapsulate_ciphertext_size(self) -> None:
        pk, _ = self.kem.keygen()
        ct, _ = self.kem.encapsulate(pk)
        # ML-KEM-768 ciphertext = 1088 bytes
        assert len(ct) == 1088

    def test_encapsulate_shared_secret_size(self) -> None:
        pk, _ = self.kem.keygen()
        _, ss = self.kem.encapsulate(pk)
        assert len(ss) == 32

    def test_decapsulate_shared_secret_size(self) -> None:
        pk, sk = self.kem.keygen()
        ct, _ = self.kem.encapsulate(pk)
        ss = self.kem.decapsulate(ct, sk)
        assert len(ss) == 32


class TestMLKEM768KemRoundTrip:
    """Verify encapsulate and decapsulate produce the same shared secret."""

    kem: MLKEM768Kem

    def setup_method(self) -> None:
        self.kem = MLKEM768Kem()

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


class TestMLKEM768KemDeterminism:
    """Verify decapsulate produces deterministic output."""

    kem: MLKEM768Kem

    def setup_method(self) -> None:
        self.kem = MLKEM768Kem()

    def test_decapsulate_is_deterministic(self) -> None:
        pk, sk = self.kem.keygen()
        ct, ss1 = self.kem.encapsulate(pk)
        # Encapsulate is non-deterministic (uses fresh randomness each time)
        # but decapsulate must be deterministic given the same (ct, sk)
        ss_dec1 = self.kem.decapsulate(ct, sk)
        ss_dec2 = self.kem.decapsulate(ct, sk)
        assert ss_dec1 == ss_dec2

    def test_encapsulate_is_non_deterministic(self) -> None:
        pk, _ = self.kem.keygen()
        ct1, _ = self.kem.encapsulate(pk)
        ct2, _ = self.kem.encapsulate(pk)
        # Different randomness each time → different ciphertexts
        assert ct1 != ct2


class TestMakeFastKem:
    """Verify make_fast_kem() returns MLKEM768Kem."""

    def test_make_fast_kem_returns_mlkem768(self) -> None:
        from libp2p.security.noise.pq.kem_backends import make_fast_kem

        kem = make_fast_kem()
        assert isinstance(kem, MLKEM768Kem)
