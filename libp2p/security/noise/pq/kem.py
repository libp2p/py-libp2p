"""
ML-KEM-768 KEM for the Noise XXhfs handshake.

The suite is ``Noise_XXhfs_25519+ML-KEM-768_ChaChaPoly_SHA256``
(protocol id ``/noise-mlkem768-hfs/0.1.0``, libp2p/specs#723).

Hybridisation happens at the protocol level, not inside the KEM: X25519 covers
the DH tokens (ee, es, se) and ML-KEM-768 fills the HFS tokens (e1, ekem1).
The KEM slot therefore carries raw ML-KEM-768 with no combiner.

  - Public key:  1184 B
  - Secret key:  2400 B
  - Ciphertext:  1088 B
  - Shared secret: 32 B
"""

from typing import Protocol, runtime_checkable

# Key and ciphertext size constants
_ML_KEM_PK_SIZE = 1184
_ML_KEM_SK_SIZE = 2400
_ML_KEM_CT_SIZE = 1088

MLKEM768_PK_SIZE = _ML_KEM_PK_SIZE  # 1184
MLKEM768_SK_SIZE = _ML_KEM_SK_SIZE  # 2400
MLKEM768_CT_SIZE = _ML_KEM_CT_SIZE  # 1088


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
