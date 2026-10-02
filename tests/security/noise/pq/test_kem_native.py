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

from collections.abc import Callable, Generator
import hashlib
import logging
import os
from types import ModuleType

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


#: Ways of getting a wrong 1088-byte ciphertext, for the implicit-rejection
#: parity check. Anything other than a single flipped bit exercises a
#: different path through FIPS 203's re-encryption comparison.
_CORRUPTIONS = [
    pytest.param(lambda ct: bytes([ct[0] ^ 0x01]) + ct[1:], id="first-byte-low-bit"),
    pytest.param(lambda ct: bytes([ct[0] ^ 0x80]) + ct[1:], id="first-byte-high-bit"),
    pytest.param(lambda ct: ct[:-1] + bytes([ct[-1] ^ 0x01]), id="last-byte"),
    pytest.param(
        lambda ct: ct[:544] + bytes([ct[544] ^ 0xFF]) + ct[545:], id="middle-byte"
    ),
    pytest.param(lambda ct: bytes(1088), id="all-zero"),
    pytest.param(lambda ct: b"\xff" * 1088, id="all-ones"),
    pytest.param(lambda ct: bytes(b ^ 0xFF for b in ct), id="bitwise-inverse"),
    pytest.param(lambda ct: ct[544:] + ct[:544], id="halves-swapped"),
]


def _load_real_mlkem() -> ModuleType:
    """The genuine ``cryptography`` ML-KEM module, bypassing any monkeypatch."""
    from cryptography.hazmat.primitives.asymmetric import mlkem

    return mlkem


def _unsupported_mlkem_module() -> object:
    """
    A stand-in for ``cryptography`` built without ML-KEM support.

    Every entry point cryptography gates on its internal support check raises
    ``UnsupportedAlgorithm``, which is what such a build really does. Fed in
    through the ``_load_native_mlkem`` seam so the unsupported case is
    reachable without uninstalling anything.
    """
    from cryptography.exceptions import UnsupportedAlgorithm

    def _unsupported(*_args: object, **_kwargs: object) -> object:
        raise UnsupportedAlgorithm("simulated: OpenSSL without ML-KEM")

    class _UnsupportedPrivateKey:
        generate = staticmethod(_unsupported)
        from_seed_bytes = staticmethod(_unsupported)

    class _UnsupportedPublicKey:
        from_public_bytes = staticmethod(_unsupported)

    class _UnsupportedModule:
        MLKEM768PrivateKey = _UnsupportedPrivateKey
        MLKEM768PublicKey = _UnsupportedPublicKey

    return _UnsupportedModule()


@pytest.fixture(autouse=True)
def _clear_backend_selection_cache() -> Generator[None, None, None]:
    """
    Reset the cached backend selection around every test in this module.

    ``make_fast_kem()`` memoises which backend it picked, so a test that
    monkeypatches the availability of a backend would otherwise either read a
    stale answer or leave one behind for the next test.
    """
    from libp2p.security.noise.pq.kem_backends import _select_kem_class

    _select_kem_class.cache_clear()
    yield
    _select_kem_class.cache_clear()


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

    @pytest.mark.parametrize("corrupt", _CORRUPTIONS)
    def test_implicit_rejection_agrees_for_every_kind_of_corruption(
        self, corrupt: Callable[[bytes], bytes]
    ) -> None:
        # One flipped bit exercises one path through the re-encryption check.
        # Implicit rejection has to be byte-identical across the backends for
        # any wrong ciphertext, including ones that are not a near-miss of a
        # real one, because the rejection secret is mixed straight into the
        # handshake transcript: a divergence would desynchronise the two peers
        # only under attack, which is the worst place to find it.
        pk, native_sk, pure_sk = _matched_keypair()
        good = _fixed_ciphertext(pk)
        bad = corrupt(good)
        assert len(bad) == 1088 and bad != good

        native_ss = self.native.decapsulate(bad, native_sk)
        pure_ss = self.pure.decapsulate(bad, pure_sk)
        assert len(native_ss) == 32
        assert native_ss == pure_ss, "implicit rejection diverged between backends"
        assert native_ss.hex() != KAT_SHARED_SECRET, (
            "a corrupt ciphertext must not recover the real shared secret"
        )

    @pytest.mark.parametrize(
        ("name", "encapsulation_key", "is_valid"),
        [
            # Correct length, and a valid ML-KEM encoding: FIPS 203's modulus
            # check passes, so both backends encapsulate to it.
            ("all-zero", b"\x00" * 1184, True),
            # Correct length but not a valid encoding: every 12-bit
            # coefficient decodes to 4095, which fails the modulus check.
            ("all-ones", b"\xff" * 1184, False),
            ("random", None, False),  # os.urandom, filled in by the test
        ],
    )
    def test_structurally_invalid_encapsulation_keys_agree_across_backends(
        self, name: str, encapsulation_key: bytes | None, is_valid: bool
    ) -> None:
        # Length is only the outer check. A 1184-byte blob that is not a valid
        # encapsulation key has to be treated the same way by both backends,
        # or a peer's handshake would succeed or fail depending on which
        # backend it happened to load.
        ek = os.urandom(1184) if encapsulation_key is None else encapsulation_key

        if is_valid:
            native_ct, native_ss = self.native.encapsulate(ek)
            pure_ct, pure_ss = self.pure.encapsulate(ek)
            assert len(native_ct) == len(pure_ct) == 1088
            assert len(native_ss) == len(pure_ss) == 32
            return

        with pytest.raises(ValueError):
            self.native.encapsulate(ek)
        with pytest.raises(ValueError):
            self.pure.encapsulate(ek)


class TestNativeKemFailsClosed:
    """
    Malformed inputs must raise, not silently produce a key.

    Each expectation matches this wrapper's own wording rather than just the
    size it mentions. ``cryptography`` prints "An ML-KEM-768 public key is
    1184 bytes long" and similar, so a match on the bare number still passes
    when our guard has been deleted and the error came from underneath.
    """

    kem: MLKEM768NativeKem

    def setup_method(self) -> None:
        self.kem = MLKEM768NativeKem()

    @pytest.mark.parametrize("length", [0, 32, 1183, 1185, 2400])
    def test_encapsulate_rejects_wrong_length_public_key(self, length: int) -> None:
        with pytest.raises(
            ValueError,
            match=rf"^ML-KEM-768 public key must be 1184 bytes, got {length}$",
        ):
            self.kem.encapsulate(b"\x00" * length)

    @pytest.mark.parametrize("length", [0, 32, 1087, 1089, 2400])
    def test_decapsulate_rejects_wrong_length_ciphertext(self, length: int) -> None:
        _, sk = self.kem.keygen()
        with pytest.raises(
            ValueError,
            match=rf"^ML-KEM-768 ciphertext must be 1088 bytes, got {length}$",
        ):
            self.kem.decapsulate(b"\x00" * length, sk)

    @pytest.mark.parametrize("length", [0, 32, 63, 65, 2400])
    def test_decapsulate_rejects_wrong_length_secret_key(self, length: int) -> None:
        pk, _ = self.kem.keygen()
        ct, _ = self.kem.encapsulate(pk)
        with pytest.raises(
            ValueError,
            match=(
                r"^native ML-KEM-768 secret key must be the 64-byte "
                rf"FIPS 203 seed, got {length}$"
            ),
        ):
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
        # touched. That must fall back, not crash a handshake later.
        #
        # The second half checks the selection is not sticky across a change
        # in the environment: it is cached, so the cache has to be cleared
        # between the two halves the same way the fixture clears it.
        from libp2p.security.noise.pq import kem as kem_module
        from libp2p.security.noise.pq.kem_backends import (
            _select_kem_class,
            make_fast_kem,
        )

        real_loader = kem_module._load_native_mlkem

        monkeypatch.setattr(
            kem_module, "_load_native_mlkem", lambda: _unsupported_mlkem_module()
        )
        assert isinstance(make_fast_kem(), MLKEM768Kem)

        monkeypatch.setattr(kem_module, "_load_native_mlkem", real_loader)
        _select_kem_class.cache_clear()
        assert isinstance(make_fast_kem(), MLKEM768NativeKem)

    def test_the_probe_detects_an_unsupported_build(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Whatever the probe calls, it has to be something cryptography gates
        # on its internal ML-KEM support check, or an unsupported build would
        # be selected and then fail mid-handshake.
        from libp2p.security.noise.pq import kem as kem_module

        monkeypatch.setattr(
            kem_module, "_load_native_mlkem", lambda: _unsupported_mlkem_module()
        )
        with pytest.raises(ImportError, match="no ML-KEM support"):
            MLKEM768NativeKem()

    def test_the_probe_does_not_generate_a_throwaway_keypair(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Generating a key to find out whether keys can be generated cost
        # ~300 us, about three times a real encapsulation, on every call.
        from libp2p.security.noise.pq import kem as kem_module

        real = _load_real_mlkem()

        class _NoKeygenPrivateKey:
            @staticmethod
            def generate() -> object:
                raise AssertionError("the support probe must not generate a key")

            @staticmethod
            def from_seed_bytes(data: bytes) -> object:
                raise AssertionError("the support probe must not expand a seed")

        class _NoKeygenModule:
            MLKEM768PrivateKey = _NoKeygenPrivateKey
            MLKEM768PublicKey = real.MLKEM768PublicKey

        monkeypatch.setattr(kem_module, "_load_native_mlkem", lambda: _NoKeygenModule())
        MLKEM768NativeKem()  # must not raise

    def test_the_backend_selection_is_cached(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # transport_pq.get_pattern() used to select a backend per connection,
        # so an unauthenticated peer could make a listener re-probe
        # cryptography on every dial.
        from libp2p.security.noise.pq import kem as kem_module
        from libp2p.security.noise.pq.kem_backends import make_fast_kem

        probes = 0

        def _counting_loader() -> object:
            nonlocal probes
            probes = probes + 1
            raise ImportError("simulated: cryptography has no mlkem module")

        monkeypatch.setattr(kem_module, "_load_native_mlkem", _counting_loader)
        assert isinstance(make_fast_kem(), MLKEM768Kem)
        assert isinstance(make_fast_kem(), MLKEM768Kem)
        assert isinstance(make_fast_kem(), MLKEM768Kem)
        assert probes == 1, (
            f"the backend selection must be probed once, not per call; "
            f"probed {probes} times"
        )

    def test_a_non_import_failure_does_not_escape_raw(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A guard that only catches ImportError lets an AttributeError from a
        # renamed upstream symbol, or an OpenSSL InternalError, propagate out
        # of make_fast_kem() instead of falling back.
        from libp2p.security.noise.pq import kem as kem_module
        from libp2p.security.noise.pq.kem_backends import make_fast_kem

        def _attribute_error() -> object:
            raise AttributeError("simulated: upstream renamed MLKEM768PrivateKey")

        monkeypatch.setattr(kem_module, "_load_native_mlkem", _attribute_error)
        assert isinstance(make_fast_kem(), MLKEM768Kem)

    def test_the_fallback_is_logged_as_a_warning_naming_the_consequence(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        # kyber-py's own metadata says it must not be used for cryptographic
        # applications and is not constant time, so silently dropping onto it
        # at DEBUG hides a real change in the security properties of the node.
        from libp2p.security.noise.pq import kem as kem_module
        from libp2p.security.noise.pq.kem_backends import make_fast_kem

        monkeypatch.setattr(
            kem_module,
            "_load_native_mlkem",
            lambda: (_ for _ in ()).throw(ImportError("simulated")),
        )
        with caplog.at_level(
            logging.DEBUG, logger="libp2p.security.noise.pq.kem_backends"
        ):
            assert isinstance(make_fast_kem(), MLKEM768Kem)

        warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert warnings, "falling back to kyber-py must not be a DEBUG-level event"
        text = " ".join(r.getMessage() for r in warnings)
        assert "kyber-py" in text
        assert "constant" in text, "the warning must name the consequence"
        assert "cryptography" in text, "the warning must name the remedy"

    def test_both_backends_missing_raises_one_error_naming_both(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from libp2p.security.noise.pq import kem as kem_module
        from libp2p.security.noise.pq.kem_backends import make_fast_kem

        def _no_native() -> object:
            raise ImportError("simulated: cryptography has no mlkem module")

        def _no_kyber(self: object) -> None:
            raise ImportError("simulated: kyber-py is not installed")

        monkeypatch.setattr(kem_module, "_load_native_mlkem", _no_native)
        monkeypatch.setattr(kem_module.MLKEM768Kem, "__init__", _no_kyber)

        with pytest.raises(ImportError) as excinfo:
            make_fast_kem()

        message = str(excinfo.value)
        assert "cryptography" in message, "the error must name the native cause"
        assert "kyber-py" in message, "the error must name the fallback cause"
        assert "libp2p[pq]" in message, "the error must say how to fix it"
