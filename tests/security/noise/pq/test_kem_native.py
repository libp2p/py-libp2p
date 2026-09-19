"""
Tests for MLKEM768NativeKem, the native ML-KEM-768 backend.

The native backend uses ``cryptography.hazmat.primitives.asymmetric.mlkem``,
which is built on the C library underneath ``cryptography`` rather than on
pure Python. The property that matters is cross-backend interoperability: a
ciphertext produced by either backend must decapsulate to the same shared
secret under the other, because a py-libp2p peer on the native backend has to
speak to a peer on the pure-Python one.

Follows TDD: these tests are written before the implementation and initially
fail.

Two asymmetries between the backends are deliberate and pinned here:

* ``encapsulate()`` ordering. ``cryptography`` returns
  ``(shared_secret, ciphertext)``; kyber-py returns ``(ss, ct)`` as well; the
  ``IKem`` contract is ``(ciphertext, shared_secret)``. Both backends have to
  swap. Transposing the pair would put a 1088-byte ciphertext where a 32-byte
  key belongs, so it is pinned by an explicit guard below.
* Secret key representation. ``cryptography`` exposes only the 64-byte FIPS 203
  seed (``d || z``) and has no API for the 2400-byte expanded decapsulation
  key, so the native backend's ``sk`` is 64 bytes where the pure-Python one is
  2400. The secret key never goes on the wire, so this does not affect
  interoperability; only ``pk`` (1184) and ``ct`` (1088) are wire formats.
"""

import hashlib

import pytest

from libp2p.security.noise.pq.kem import (
    IKem,
    MLKEM768Kem,
    MLKEM768NativeKem,
)

# ---------------------------------------------------------------------------
# Deterministic vector, derived from the pure-Python backend
#
# The expected values below were computed with kyber-py, the backend that the
# committed fixture tests/fixtures/mlkem768-xxhfs-vectors.json already pins, so
# they are an independent expectation for the native backend rather than a
# recording of it.
# ---------------------------------------------------------------------------

KAT_SEED = hashlib.sha512(b"py-libp2p XXhfs native-backend parity seed v1").digest()
KAT_ENCAP_RANDOMNESS = hashlib.sha256(
    b"py-libp2p XXhfs native-backend parity encap randomness v1"
).digest()

KAT_EK_SHA256 = "b79c9d7ac953518bf3882c55fabfd62b47d5ed17545ac8ef38e4e81a4f6a12c2"
KAT_CT_SHA256 = "b496abe70b7cc3333add4229353729efb023642e09133dc3128fccfaa7fa4c92"
KAT_SHARED_SECRET = "0dcf4a8e1a7cfecec726bf8e23e047c2b2252ad783da06c30cb8846bf07b65bc"
KAT_IMPLICIT_REJECTION = (
    "f818137a6bb72446ed6cf5fa6fe103b579214e54145171882791fdef98a65cc7"
)


def _matched_keypair() -> tuple[bytes, bytes, bytes]:
    """
    Build one ML-KEM-768 keypair in both backends' secret-key representations.

    Returns ``(pk, native_sk, pure_sk)``. The two backends hold the same key,
    but ``cryptography`` stores the 64-byte seed and kyber-py the 2400-byte
    expanded decapsulation key, so the seeded key-derivation entry points of
    the two libraries are used directly. There is no other way to get a single
    keypair usable by both.
    """
    from cryptography.hazmat.primitives.asymmetric import mlkem
    from kyber_py.ml_kem import ML_KEM_768

    native_key = mlkem.MLKEM768PrivateKey.from_seed_bytes(KAT_SEED)
    native_pk = native_key.public_key().public_bytes_raw()
    pure_pk, pure_sk = ML_KEM_768.key_derive(KAT_SEED)
    assert native_pk == bytes(pure_pk), (
        "the two libraries disagree on seeded key derivation, so no shared "
        "keypair exists and the rest of this module is meaningless"
    )
    return native_pk, KAT_SEED, bytes(pure_sk)


def _fixed_ciphertext(pk: bytes) -> bytes:
    """
    Produce the pinned ciphertext with kyber-py's FIPS 203 deterministic
    encapsulation, so both backends can be asked to decapsulate the same bytes.
    """
    from kyber_py.ml_kem import ML_KEM_768

    _ss, ct = ML_KEM_768._encaps_internal(pk, KAT_ENCAP_RANDOMNESS)
    return bytes(ct)


class TestMLKEM768NativeKemShape:
    """Sizes, types and the IKem contract."""

    kem: MLKEM768NativeKem

    def setup_method(self) -> None:
        self.kem = MLKEM768NativeKem()

    def test_satisfies_the_ikem_protocol(self) -> None:
        assert isinstance(self.kem, IKem)

    def test_keygen_public_key_is_1184_bytes(self) -> None:
        pk, _ = self.kem.keygen()
        assert isinstance(pk, bytes)
        assert len(pk) == 1184

    def test_keygen_secret_key_is_the_64_byte_fips_203_seed(self) -> None:
        # cryptography exposes only the seed (d || z), not the 2400-byte
        # expanded decapsulation key that kyber-py returns.
        _, sk = self.kem.keygen()
        assert isinstance(sk, bytes)
        assert len(sk) == 64

    def test_keygen_is_not_constant(self) -> None:
        pk1, sk1 = self.kem.keygen()
        pk2, sk2 = self.kem.keygen()
        assert pk1 != pk2
        assert sk1 != sk2

    def test_encapsulate_ciphertext_is_1088_bytes(self) -> None:
        pk, _ = self.kem.keygen()
        ct, _ = self.kem.encapsulate(pk)
        assert isinstance(ct, bytes)
        assert len(ct) == 1088

    def test_encapsulate_shared_secret_is_32_bytes(self) -> None:
        pk, _ = self.kem.keygen()
        _, ss = self.kem.encapsulate(pk)
        assert isinstance(ss, bytes)
        assert len(ss) == 32

    def test_round_trip(self) -> None:
        pk, sk = self.kem.keygen()
        ct, ss_enc = self.kem.encapsulate(pk)
        assert self.kem.decapsulate(ct, sk) == ss_enc

    def test_decapsulate_is_deterministic(self) -> None:
        pk, sk = self.kem.keygen()
        ct, _ = self.kem.encapsulate(pk)
        assert self.kem.decapsulate(ct, sk) == self.kem.decapsulate(ct, sk)

    def test_encapsulate_is_non_deterministic(self) -> None:
        pk, _ = self.kem.keygen()
        ct1, _ = self.kem.encapsulate(pk)
        ct2, _ = self.kem.encapsulate(pk)
        assert ct1 != ct2


class TestEncapsulateReturnOrder:
    """
    Guard against transposing encapsulate()'s return pair.

    ``cryptography`` returns ``(shared_secret, ciphertext)``; ``IKem`` requires
    ``(ciphertext, shared_secret)``. Returning the library's tuple unswapped
    would hand a 32-byte value to the wire as a ciphertext and a 1088-byte
    value to the symmetric state as a key, which the handshake would only
    notice as an opaque failure at the far end. Every assertion here fails if
    the pair is transposed.
    """

    kem: MLKEM768NativeKem

    def setup_method(self) -> None:
        self.kem = MLKEM768NativeKem()

    def test_first_element_is_the_ciphertext_not_the_shared_secret(self) -> None:
        pk, _ = self.kem.keygen()
        first, second = self.kem.encapsulate(pk)
        assert len(first) == 1088, "first element must be the 1088-byte ciphertext"
        assert len(second) == 32, "second element must be the 32-byte shared secret"

    def test_first_element_decapsulates_to_the_second(self) -> None:
        pk, sk = self.kem.keygen()
        first, second = self.kem.encapsulate(pk)
        assert self.kem.decapsulate(first, sk) == second

    def test_order_matches_the_pure_python_backend(self) -> None:
        pk, _ = self.kem.keygen()
        native_first, native_second = self.kem.encapsulate(pk)
        pure_first, pure_second = MLKEM768Kem().encapsulate(pk)
        assert len(native_first) == len(pure_first)
        assert len(native_second) == len(pure_second)

    def test_swapping_the_library_tuple_is_what_we_correct(self) -> None:
        # Pin the upstream ordering this backend has to correct, so that an
        # upstream change is caught here rather than on the wire.
        from cryptography.hazmat.primitives.asymmetric import mlkem

        key = mlkem.MLKEM768PrivateKey.generate()
        library_first, library_second = key.public_key().encapsulate()
        assert len(library_first) == 32, "cryptography returns the secret first"
        assert len(library_second) == 1088, "cryptography returns the ciphertext second"


class TestCrossBackendInterop:
    """A ciphertext from either backend must work under the other."""

    native: MLKEM768NativeKem
    pure: MLKEM768Kem

    def setup_method(self) -> None:
        self.native = MLKEM768NativeKem()
        self.pure = MLKEM768Kem()

    def test_seeded_key_derivation_agrees(self) -> None:
        pk, _native_sk, _pure_sk = _matched_keypair()
        assert hashlib.sha256(pk).hexdigest() == KAT_EK_SHA256

    def test_native_ciphertext_decapsulates_under_pure_python(self) -> None:
        pk, _native_sk, pure_sk = _matched_keypair()
        ct, ss_native = self.native.encapsulate(pk)
        assert self.pure.decapsulate(ct, pure_sk) == ss_native

    def test_pure_python_ciphertext_decapsulates_under_native(self) -> None:
        pk, native_sk, _pure_sk = _matched_keypair()
        ct, ss_pure = self.pure.encapsulate(pk)
        assert self.native.decapsulate(ct, native_sk) == ss_pure

    def test_fixed_ciphertext_gives_the_pinned_shared_secret_on_both(self) -> None:
        pk, native_sk, pure_sk = _matched_keypair()
        ct = _fixed_ciphertext(pk)
        assert hashlib.sha256(ct).hexdigest() == KAT_CT_SHA256
        assert self.native.decapsulate(ct, native_sk).hex() == KAT_SHARED_SECRET
        assert self.pure.decapsulate(ct, pure_sk).hex() == KAT_SHARED_SECRET

    def test_corrupt_ciphertext_implicitly_rejects_identically(self) -> None:
        # ML-KEM is IND-CCA2 with implicit rejection: a corrupt ciphertext
        # yields a pseudorandom secret rather than an error, and FIPS 203 makes
        # that value deterministic, so both backends must return the same one.
        pk, native_sk, pure_sk = _matched_keypair()
        ct = bytearray(_fixed_ciphertext(pk))
        ct[0] ^= 0x01
        corrupt = bytes(ct)
        native_ss = self.native.decapsulate(corrupt, native_sk)
        pure_ss = self.pure.decapsulate(corrupt, pure_sk)
        assert native_ss.hex() == KAT_IMPLICIT_REJECTION
        assert pure_ss == native_ss
        assert native_ss.hex() != KAT_SHARED_SECRET


class TestNativeKemFailsClosed:
    """Malformed inputs must raise, not silently produce a key."""

    kem: MLKEM768NativeKem

    def setup_method(self) -> None:
        self.kem = MLKEM768NativeKem()

    @pytest.mark.parametrize("length", [0, 32, 1183, 1185, 2400])
    def test_encapsulate_rejects_wrong_length_public_key(self, length: int) -> None:
        with pytest.raises(ValueError, match="1184"):
            self.kem.encapsulate(b"\x00" * length)

    @pytest.mark.parametrize("length", [0, 32, 1087, 1089, 2400])
    def test_decapsulate_rejects_wrong_length_ciphertext(self, length: int) -> None:
        _, sk = self.kem.keygen()
        with pytest.raises(ValueError, match="1088"):
            self.kem.decapsulate(b"\x00" * length, sk)

    @pytest.mark.parametrize("length", [0, 32, 63, 65, 2400])
    def test_decapsulate_rejects_wrong_length_secret_key(self, length: int) -> None:
        pk, _ = self.kem.keygen()
        ct, _ = self.kem.encapsulate(pk)
        with pytest.raises(ValueError, match="64"):
            self.kem.decapsulate(ct, b"\x00" * length)

    def test_both_backends_reject_a_wrong_length_public_key(self) -> None:
        # The pure-Python backend already fails closed here; the native one
        # must not be laxer.
        short = b"\x00" * 1183
        with pytest.raises(ValueError):
            MLKEM768Kem().encapsulate(short)
        with pytest.raises(ValueError):
            self.kem.encapsulate(short)

    def test_both_backends_reject_a_wrong_length_ciphertext(self) -> None:
        pk, native_sk, pure_sk = _matched_keypair()
        short = _fixed_ciphertext(pk)[:-1]
        with pytest.raises(ValueError):
            MLKEM768Kem().decapsulate(short, pure_sk)
        with pytest.raises(ValueError):
            self.kem.decapsulate(short, native_sk)


class TestPublicExport:
    """The native backend is part of the package's public API."""

    def test_exported_from_the_pq_package(self) -> None:
        import libp2p.security.noise.pq as pq

        assert "MLKEM768NativeKem" in pq.__all__
        assert pq.MLKEM768NativeKem is MLKEM768NativeKem


class TestMakeFastKemSelection:
    """make_fast_kem() prefers the native backend and falls back cleanly."""

    def test_returns_the_native_backend_when_available(self) -> None:
        from libp2p.security.noise.pq.kem_backends import make_fast_kem

        assert isinstance(make_fast_kem(), MLKEM768NativeKem)

    def test_falls_back_to_pure_python_when_native_is_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from libp2p.security.noise.pq import kem as kem_module
        from libp2p.security.noise.pq.kem_backends import make_fast_kem

        def _no_native() -> object:
            raise ImportError("simulated: cryptography has no mlkem module")

        monkeypatch.setattr(kem_module, "_load_native_mlkem", _no_native)
        kem = make_fast_kem()
        assert isinstance(kem, MLKEM768Kem)
        assert not isinstance(kem, MLKEM768NativeKem)

    def test_native_backend_raises_importerror_when_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from libp2p.security.noise.pq import kem as kem_module

        def _no_native() -> object:
            raise ImportError("simulated: cryptography has no mlkem module")

        monkeypatch.setattr(kem_module, "_load_native_mlkem", _no_native)
        with pytest.raises(ImportError, match="cryptography"):
            MLKEM768NativeKem()

    def test_falls_back_when_the_build_lacks_ml_kem_support(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # cryptography >= 48 always ships the module, but a build against
        # OpenSSL < 3.5 raises UnsupportedAlgorithm the first time a key is
        # generated. That must fall back, not crash a handshake later.
        from cryptography.exceptions import UnsupportedAlgorithm

        from libp2p.security.noise.pq import kem as kem_module
        from libp2p.security.noise.pq.kem_backends import make_fast_kem

        real_loader = kem_module._load_native_mlkem

        class _UnsupportedPrivateKey:
            @staticmethod
            def generate() -> object:
                raise UnsupportedAlgorithm("simulated: OpenSSL without ML-KEM")

        class _UnsupportedPublicKey:
            pass

        class _UnsupportedModule:
            MLKEM768PrivateKey = _UnsupportedPrivateKey
            MLKEM768PublicKey = _UnsupportedPublicKey

        monkeypatch.setattr(
            kem_module, "_load_native_mlkem", lambda: _UnsupportedModule()
        )
        assert isinstance(make_fast_kem(), MLKEM768Kem)
        monkeypatch.setattr(kem_module, "_load_native_mlkem", real_loader)
        assert isinstance(make_fast_kem(), MLKEM768NativeKem)
