"""
ML-KEM-768 KEM for the Noise XXhfs handshake.

The suite is ``Noise_XXhfs_25519+MLKEM768_ChaChaPoly_SHA256``, specified in
libp2p/specs#727 (Stage 1A Working Draft, tracked by libp2p/specs#723). The
protocol id this implementation ships is ``/noise-mlkem768-hfs/0.2.0``; #727
writes ``/noise-mlkem768-hfs/0.1.0`` and lists the identifier string as the
first of its open issues, so the id is not settled and this implementation
will follow whatever #727 concludes.

Hybridisation happens at the protocol level, not inside the KEM: X25519 covers
the DH tokens (ee, es, se) and ML-KEM-768 fills the HFS tokens (e1, ekem1).
The KEM slot therefore carries raw ML-KEM-768 with no combiner.

  - Public key:  1184 B
  - Secret key:  2400 B expanded, or the 64 B FIPS 203 (d || z) seed
  - Ciphertext:  1088 B
  - Shared secret: 32 B

Two backends implement ``IKem``: :class:`MLKEM768NativeKem`, built on
``cryptography``, and :class:`MLKEM768Kem`, pure Python via kyber-py.
``kem_backends.make_fast_kem()`` prefers the native one. They interoperate,
because only the public key and the ciphertext go on the wire and those are
identical; the secret key stays local and the two backends hold it in
different forms (2400 B expanded for kyber-py, the 64 B seed for the native
one, which exposes no API for the expanded key).
"""

from types import ModuleType
from typing import Protocol, runtime_checkable

from cryptography.exceptions import UnsupportedAlgorithm

# Key and ciphertext size constants
_ML_KEM_PK_SIZE = 1184
_ML_KEM_SK_SIZE = 2400
_ML_KEM_CT_SIZE = 1088
_ML_KEM_SEED_SIZE = 64

MLKEM768_PK_SIZE = _ML_KEM_PK_SIZE  # 1184
#: Size of the *expanded* FIPS 203 decapsulation key, which is what
#: :class:`MLKEM768Kem` (kyber-py) returns from ``keygen()``. It is NOT the
#: size of every backend's secret key: :class:`MLKEM768NativeKem` returns the
#: 64-byte seed instead (``MLKEM768_SEED_SIZE``), because ``cryptography``
#: exposes no API for the expanded form. Do not use this to validate a secret
#: key of unknown provenance; ask the backend that produced it.
MLKEM768_SK_SIZE = _ML_KEM_SK_SIZE  # 2400, kyber-py only
MLKEM768_CT_SIZE = _ML_KEM_CT_SIZE  # 1088
MLKEM768_SEED_SIZE = _ML_KEM_SEED_SIZE  # 64, the FIPS 203 (d || z) seed

# A well-formed (all-zero) encapsulation key, used only to probe whether this
# build of ``cryptography`` can run ML-KEM at all. Never used as a key.
_ZERO_ENCAPSULATION_KEY = b"\x00" * _ML_KEM_PK_SIZE


@runtime_checkable
class IKem(Protocol):
    """
    Backend-agnostic KEM interface for the XXhfs handshake.

    The public key and the ciphertext are wire formats and are identical
    across backends: 1184 and 1088 bytes of FIPS 203 encoding, which is what
    makes two peers on different backends interoperable.

    The secret key is **opaque** and **backend-specific**. It is whatever the
    backend that produced it can consume, and nothing more: kyber-py returns
    the 2400-byte expanded decapsulation key while the native backend returns
    the 64-byte FIPS 203 seed. A secret key must therefore be passed back to
    ``decapsulate()`` on the same backend instance (or at least the same
    implementation) that returned it from ``keygen()``. It never goes on the
    wire, so this costs nothing in interoperability, but a caller that caches
    or persists one must cache the backend choice with it.
    """

    def keygen(self) -> tuple[bytes, bytes]:
        """
        Generate a KEM key pair.

        Returns:
            (public_key, secret_key) as raw bytes. ``secret_key`` is opaque
            and only meaningful to this backend; see the class docstring.

        """
        ...

    def encapsulate(self, pk: bytes) -> tuple[bytes, bytes]:
        """
        Encapsulate a shared secret to a public key.

        Args:
            pk: Recipient's public key.

        Returns:
            (ciphertext, shared_secret) as raw bytes.

        """
        ...

    def decapsulate(self, ct: bytes, sk: bytes) -> bytes:
        """
        Decapsulate a shared secret from a ciphertext.

        Args:
            ct: Ciphertext from the encapsulator.
            sk: Secret key from this backend's ``keygen()``; encoding is opaque.

        Returns:
            Shared secret as 32 raw bytes.

        """
        ...


class MLKEM768Kem:
    """
    Raw ML-KEM-768 KEM (no X25519 hybrid wrapper).

    The hybridization in Noise XXhfs happens at the protocol level: ML-KEM-768
    provides the KEM token (ekem1) while X25519 provides the DH tokens (ee, es, se).
    No combiner is needed inside the KEM.

    Uses kyber-py as the ML-KEM-768 backend.
    Requires the ``kyber-py`` package (``pip install 'libp2p[pq]'``).
    The import is deferred to construction time so modules importing
    this class do not require kyber-py to be installed.

    IMPORTANT: kyber-py's ``ML_KEM_768.encaps(pk)`` returns ``(ss, ct)``:
    shared secret first, ciphertext second. This is reversed from the liboqs
    convention. ``encapsulate()`` corrects the order to ``(ct, ss)`` per IKem.
    """

    def __init__(self) -> None:
        try:
            from kyber_py.ml_kem import ML_KEM_768
        except ImportError as exc:
            raise ImportError(
                "MLKEM768Kem requires the 'kyber-py' package. "
                "Install it with: pip install 'libp2p[pq]'"
            ) from exc
        self._ml_kem = ML_KEM_768

    def keygen(self) -> tuple[bytes, bytes]:
        """Returns (pk, sk) where pk=1184 B, sk=2400 B."""
        pk, sk = self._ml_kem.keygen()
        return pk, sk

    def encapsulate(self, pk: bytes) -> tuple[bytes, bytes]:
        """
        Returns (ciphertext, shared_secret) where ct=1088 B, ss=32 B.

        Note: kyber-py ML_KEM_768.encaps() returns (ss, ct), so we swap the order
        to match the IKem convention of (ct, ss).
        """
        if len(pk) != MLKEM768_PK_SIZE:
            raise ValueError(
                f"ML-KEM-768 public key must be {MLKEM768_PK_SIZE} bytes, got {len(pk)}"
            )
        ss, ct = self._ml_kem.encaps(pk)  # kyber-py returns (ss, ct)
        return ct, ss

    def decapsulate(self, ct: bytes, sk: bytes) -> bytes:
        """Returns shared_secret (32 bytes)."""
        if len(ct) != MLKEM768_CT_SIZE:
            raise ValueError(
                f"ML-KEM-768 ciphertext must be {MLKEM768_CT_SIZE} bytes, got {len(ct)}"
            )
        return self._ml_kem.decaps(sk, ct)


def _load_native_mlkem() -> ModuleType:
    """
    Import ``cryptography``'s ML-KEM module.

    Kept as a module-level function so the unavailable case is reachable in a
    test without uninstalling anything.

    Raises:
        ImportError: if the installed ``cryptography`` predates the module.

    """
    from cryptography.hazmat.primitives.asymmetric import mlkem

    return mlkem


class MLKEM768NativeKem:
    """
    Raw ML-KEM-768 KEM backed by ``cryptography``'s native implementation.

    Same wire formats as :class:`MLKEM768Kem` (1184-byte encapsulation key,
    1088-byte ciphertext, 32-byte shared secret) and the same ``IKem``
    contract, so the two backends interoperate: a ciphertext produced by
    either decapsulates to the same shared secret under the other.

    Requires ``cryptography >= 48.0.0``, which is the first release whose
    wheels can actually run ML-KEM. The module was added in 47.0.0 but only
    with AWS-LC or BoringSSL underneath; 48.0.0 added OpenSSL 3.5.0+, which is
    what the published wheels ship.

    Two differences from :class:`MLKEM768Kem` are worth knowing:

    * The secret key is the 64-byte FIPS 203 seed (``d || z``), not the
      2400-byte expanded decapsulation key. ``cryptography`` exposes no API for
      the expanded form. The secret key never goes on the wire, so this does
      not affect interoperability, but a secret key is not portable between
      the two backends.
    * ``cryptography``'s ``encapsulate()`` returns ``(shared_secret,
      ciphertext)``. ``encapsulate()`` below swaps it to the ``IKem`` order of
      ``(ciphertext, shared_secret)``.
    """

    def __init__(self) -> None:
        try:
            mlkem = _load_native_mlkem()
        except ImportError as exc:
            raise ImportError(
                "MLKEM768NativeKem requires cryptography>=48.0.0 with its "
                "hazmat.primitives.asymmetric.mlkem module"
            ) from exc
        self._private_key_cls = mlkem.MLKEM768PrivateKey
        self._public_key_cls = mlkem.MLKEM768PublicKey
        # A build of cryptography against OpenSSL earlier than 3.5.0 ships the
        # module but raises UnsupportedAlgorithm the first time a key is
        # touched. Probe here so callers can fall back to the pure-Python
        # backend instead of failing mid-handshake.
        #
        # The probe parses a well-formed all-zero encapsulation key rather
        # than generating a keypair. ``cryptography`` gates ``generate()``,
        # ``from_seed_bytes()`` and ``from_public_bytes()`` on the same
        # internal ``backend.mlkem_supported()`` check, and parsing is the
        # cheapest of the three by roughly a factor of eight (~35 us against
        # ~300 us here) and allocates no key material. ``mlkem_supported()``
        # itself is cheaper still, but it lives on the hazmat OpenSSL backend
        # object, which is not part of cryptography's public API.
        try:
            self._public_key_cls.from_public_bytes(_ZERO_ENCAPSULATION_KEY)
        except UnsupportedAlgorithm as exc:
            raise ImportError(
                "this cryptography build has no ML-KEM support; it needs "
                "OpenSSL 3.5.0+, AWS-LC or BoringSSL underneath"
            ) from exc

    def keygen(self) -> tuple[bytes, bytes]:
        """Returns (pk, sk) where pk=1184 B and sk is the 64 B FIPS 203 seed."""
        key = self._private_key_cls.generate()
        return key.public_key().public_bytes_raw(), key.private_bytes_raw()

    def encapsulate(self, pk: bytes) -> tuple[bytes, bytes]:
        """
        Returns (ciphertext, shared_secret) where ct=1088 B, ss=32 B.

        Note: cryptography's ``encapsulate()`` returns ``(ss, ct)``, so we swap
        the order to match the IKem convention of ``(ct, ss)``.
        """
        if len(pk) != MLKEM768_PK_SIZE:
            raise ValueError(
                f"ML-KEM-768 public key must be {MLKEM768_PK_SIZE} bytes, got {len(pk)}"
            )
        public_key = self._public_key_cls.from_public_bytes(pk)
        ss, ct = public_key.encapsulate()  # cryptography returns (ss, ct)
        return ct, ss

    def decapsulate(self, ct: bytes, sk: bytes) -> bytes:
        """Returns shared_secret (32 bytes). ``sk`` is the 64-byte seed."""
        if len(ct) != MLKEM768_CT_SIZE:
            raise ValueError(
                f"ML-KEM-768 ciphertext must be {MLKEM768_CT_SIZE} bytes, got {len(ct)}"
            )
        if len(sk) != MLKEM768_SEED_SIZE:
            raise ValueError(
                f"native ML-KEM-768 secret key must be the "
                f"{MLKEM768_SEED_SIZE}-byte FIPS 203 seed, got {len(sk)}"
            )
        private_key = self._private_key_cls.from_seed_bytes(sk)
        return private_key.decapsulate(ct)
