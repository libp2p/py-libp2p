"""
X-Wing KEM for the Noise XXhfs handshake.

X-Wing is a hybrid KEM combining ML-KEM-768 and X25519:
  - Public key:  ML-KEM-768 encapsulation key (1184 B) || X25519 public key (32 B)
  - Secret key:  ML-KEM-768 decapsulation key (2400 B) || X25519 private key (32 B)
  - Ciphertext:  ML-KEM-768 ciphertext (1088 B) || X25519 ephemeral public key (32 B)
  - Shared secret: SHA3-256(ss_mlkem || ss_x25519 || ct_x25519 || pk_x25519 || label)

Reference: draft-connolly-cfrg-xwing-kem
"""

from typing import Protocol, runtime_checkable

from nacl.bindings import crypto_scalarmult, crypto_scalarmult_base
import nacl.utils

from ._xwing import _xwing_combine

# Key and ciphertext size constants
_ML_KEM_PK_SIZE = 1184
_ML_KEM_SK_SIZE = 2400
_ML_KEM_CT_SIZE = 1088
_X25519_KEY_SIZE = 32

XWING_PK_SIZE = _ML_KEM_PK_SIZE + _X25519_KEY_SIZE  # 1216
XWING_SK_SIZE = _ML_KEM_SK_SIZE + _X25519_KEY_SIZE  # 2432
XWING_CT_SIZE = _ML_KEM_CT_SIZE + _X25519_KEY_SIZE  # 1120


@runtime_checkable
class IKem(Protocol):
    """Backend-agnostic KEM interface for the XXhfs handshake."""

    def keygen(self) -> tuple[bytes, bytes]:
        """
        Generate a KEM key pair.

        Returns:
            (public_key, secret_key) as raw bytes.

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
            sk: Local secret key.

        Returns:
            Shared secret as 32 raw bytes.

        """
        ...


class XWingKem:
    """
    X-Wing hybrid KEM using ML-KEM-768 and X25519.

    Uses kyber-py as the ML-KEM-768 backend and PyNaCl for X25519.
    Implements the IKem protocol.

    Requires the ``kyber-py`` package (``pip install 'libp2p[pq]'``).
    The import is deferred to construction time so that modules importing
    this class do not require kyber-py to be installed.
    """

    def __init__(self) -> None:
        try:
            from kyber_py.ml_kem import ML_KEM_768
        except ImportError as exc:
            raise ImportError(
                "XWingKem requires the 'kyber-py' package. "
                "Install it with: pip install 'libp2p[pq]'"
            ) from exc
        self._ml_kem = ML_KEM_768

    def keygen(self) -> tuple[bytes, bytes]:
        """
        Generate an X-Wing key pair.

        Returns:
            (pk, sk) where:
              pk = ml_kem_ek (1184 B) || x25519_pk (32 B)  -- 1216 bytes total
              sk = ml_kem_dk (2400 B) || x25519_sk (32 B)  -- 2432 bytes total

        """
        ml_kem_pk, ml_kem_sk = self._ml_kem.keygen()

        x25519_sk = nacl.utils.random(_X25519_KEY_SIZE)
        x25519_pk = bytes(crypto_scalarmult_base(x25519_sk))

        pk = ml_kem_pk + x25519_pk
        sk = ml_kem_sk + x25519_sk
        return pk, sk

    def encapsulate(self, pk: bytes) -> tuple[bytes, bytes]:
        """
        Encapsulate a shared secret to an X-Wing public key.

        Generates a fresh X25519 ephemeral key pair each call.

        Args:
            pk: X-Wing public key (1216 bytes).

        Returns:
            (ct, ss) where:
              ct = ml_kem_ct (1088 B) || x25519_eph_pk (32 B)  -- 1120 bytes total
              ss = 32-byte combined shared secret

        Raises:
            ValueError: If pk is not 1216 bytes.

        """
        if len(pk) != XWING_PK_SIZE:
            raise ValueError(
                f"X-Wing public key must be {XWING_PK_SIZE} bytes, got {len(pk)}"
            )

        ml_kem_pk = pk[:_ML_KEM_PK_SIZE]
        x25519_pk_r = pk[_ML_KEM_PK_SIZE:]

        # ML-KEM-768 encapsulation
        ss_mlkem, ml_kem_ct = self._ml_kem.encaps(ml_kem_pk)

        # X25519 ephemeral key exchange
        x25519_eph_sk = nacl.utils.random(_X25519_KEY_SIZE)
        x25519_eph_pk = bytes(crypto_scalarmult_base(x25519_eph_sk))
        ss_x25519 = bytes(crypto_scalarmult(x25519_eph_sk, x25519_pk_r))

        ss = _xwing_combine(ss_mlkem, ss_x25519, x25519_eph_pk, x25519_pk_r)
        ct = ml_kem_ct + x25519_eph_pk
        return ct, ss

    def decapsulate(self, ct: bytes, sk: bytes) -> bytes:
        """
        Decapsulate a shared secret from an X-Wing ciphertext.

        Args:
            ct: X-Wing ciphertext (1120 bytes).
            sk: X-Wing secret key (2432 bytes).

        Returns:
            32-byte combined shared secret.

        Raises:
            ValueError: If ct or sk have unexpected lengths.

        """
        if len(ct) != XWING_CT_SIZE:
            raise ValueError(
                f"X-Wing ciphertext must be {XWING_CT_SIZE} bytes, got {len(ct)}"
            )
        if len(sk) != XWING_SK_SIZE:
            raise ValueError(
                f"X-Wing secret key must be {XWING_SK_SIZE} bytes, got {len(sk)}"
            )

        ml_kem_sk = sk[:_ML_KEM_SK_SIZE]
        x25519_sk_r = sk[_ML_KEM_SK_SIZE:]

        ml_kem_ct = ct[:_ML_KEM_CT_SIZE]
        x25519_eph_pk = ct[_ML_KEM_CT_SIZE:]

        # ML-KEM-768 decapsulation
        ss_mlkem = self._ml_kem.decaps(ml_kem_sk, ml_kem_ct)

        # X25519 DH using our static private key and the ephemeral public key
        ss_x25519 = bytes(crypto_scalarmult(x25519_sk_r, x25519_eph_pk))

        # Reconstruct our X25519 public key for the combiner
        x25519_pk_r = bytes(crypto_scalarmult_base(x25519_sk_r))

        return _xwing_combine(ss_mlkem, ss_x25519, x25519_eph_pk, x25519_pk_r)


# --- ML-KEM-768 standalone (no X25519 wrapper) ---

MLKEM768_PK_SIZE = _ML_KEM_PK_SIZE  # 1184
MLKEM768_SK_SIZE = _ML_KEM_SK_SIZE  # 2400
MLKEM768_CT_SIZE = _ML_KEM_CT_SIZE  # 1088
MLKEM768_SS_SIZE = 32


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

    IMPORTANT: kyber-py's ``ML_KEM_768.encaps(pk)`` returns ``(ss, ct)`` —
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

        Note: kyber-py ML_KEM_768.encaps() returns (ss, ct) — we swap the order
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
