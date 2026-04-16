"""
Noise symmetric state for the XXhfs handshake.

Implements CipherState and SymmetricState as defined in the Noise protocol spec
(https://noiseprotocol.org/noise.html) with ChaCha20-Poly1305 and SHA-256,
extended for the HFS (Hybrid Forward Secrecy) pattern.

Protocol name: Noise_XXhfs_25519+XWing_ChaChaPoly_SHA256
"""

import hashlib
import hmac
import struct

from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

# Full protocol name -- cryptographically bound to every derived key
PROTOCOL_NAME = b"Noise_XXhfs_25519+XWing_ChaChaPoly_SHA256"

_HASH_LEN = 32   # SHA-256 output length
_KEY_LEN = 32    # ChaCha20 key length
_TAG_LEN = 16    # Poly1305 tag length


def _hmac_sha256(key: bytes, data: bytes) -> bytes:
    return hmac.new(key, data, hashlib.sha256).digest()


def _hkdf(chaining_key: bytes, input_key_material: bytes, n: int) -> tuple[bytes, ...]:
    """
    Noise HKDF producing n outputs (2 or 3), each 32 bytes.

    temp_k = HMAC-SHA256(ck, ikm)
    out_i  = HMAC-SHA256(temp_k, out_{i-1} || byte(i))
    """
    temp_k = _hmac_sha256(chaining_key, input_key_material)
    out1 = _hmac_sha256(temp_k, b"\x01")
    out2 = _hmac_sha256(temp_k, out1 + b"\x02")
    if n == 2:
        return out1, out2
    out3 = _hmac_sha256(temp_k, out2 + b"\x03")
    return out1, out2, out3


def _nonce_bytes(n: int) -> bytes:
    """Encode Noise nonce: 4 zero bytes + 8-byte little-endian counter = 12 bytes."""
    return b"\x00" * 4 + struct.pack("<Q", n)


class CipherState:
    """
    Noise CipherState using ChaCha20-Poly1305.

    Holds a key and a monotonically increasing nonce counter.
    Each encrypt/decrypt call increments the counter.
    """

    n: int

    def __init__(self, key: bytes) -> None:
        if len(key) != _KEY_LEN:
            raise ValueError(f"Key must be {_KEY_LEN} bytes, got {len(key)}")
        self._cipher = ChaCha20Poly1305(key)
        self.n = 0

    def encrypt_with_ad(self, ad: bytes, plaintext: bytes) -> bytes:
        """Encrypt plaintext with associated data. Increments nonce counter."""
        ct = self._cipher.encrypt(_nonce_bytes(self.n), plaintext, ad)
        self.n += 1
        return ct

    def decrypt_with_ad(self, ad: bytes, ciphertext: bytes) -> bytes:
        """Decrypt ciphertext with associated data. Increments nonce counter."""
        plaintext = self._cipher.decrypt(_nonce_bytes(self.n), ciphertext, ad)
        self.n += 1
        return plaintext


class SymmetricState:
    """
    Noise SymmetricState for Noise_XXhfs_25519+XWing_ChaChaPoly_SHA256.

    Maintains the chaining key (ck) and handshake hash (h) across all
    message tokens. Both are initialised to SHA-256(PROTOCOL_NAME).
    """

    ck: bytes   # chaining key
    h: bytes    # handshake hash (running transcript)
    _cs: CipherState | None

    def __init__(self) -> None:
        # Protocol name > 32 bytes so h = HASH(protocol_name)
        digest = hashlib.sha256(PROTOCOL_NAME).digest()
        self.ck = digest
        self.h = digest
        self._cs = None

    def mix_hash(self, data: bytes) -> None:
        """h = SHA-256(h || data)"""
        self.h = hashlib.sha256(self.h + data).digest()

    def mix_key(self, input_key_material: bytes) -> None:
        """Update chaining key and cipher key via HKDF."""
        self.ck, temp_k = _hkdf(self.ck, input_key_material, 2)
        self._cs = CipherState(temp_k)

    def mix_key_and_hash(self, input_key_material: bytes) -> None:
        """
        3-output HKDF for HFS tokens (used with KEM shared secret).

        ck, temp_h, temp_k = HKDF(ck, ss, 3)
        MixHash(temp_h)
        """
        self.ck, temp_h, temp_k = _hkdf(self.ck, input_key_material, 3)
        self.mix_hash(temp_h)
        self._cs = CipherState(temp_k)

    def encrypt_and_hash(self, plaintext: bytes) -> bytes:
        """
        AEAD-encrypt plaintext, then mix the ciphertext into h.

        Returns the ciphertext (plaintext + 16-byte tag).
        """
        if self._cs is None:
            # No key yet -- send in the clear (used for early tokens)
            self.mix_hash(plaintext)
            return plaintext
        ct = self._cs.encrypt_with_ad(self.h, plaintext)
        self.mix_hash(ct)
        return ct

    def decrypt_and_hash(self, ciphertext: bytes) -> bytes:
        """
        AEAD-decrypt ciphertext, then mix the ciphertext into h.

        Returns the plaintext.
        """
        if self._cs is None:
            self.mix_hash(ciphertext)
            return ciphertext
        plaintext = self._cs.decrypt_with_ad(self.h, ciphertext)
        self.mix_hash(ciphertext)
        return plaintext

    def split(self) -> tuple[CipherState, CipherState]:
        """
        Derive two transport CipherStates at the end of the handshake.

        Returns (initiator_cs, responder_cs).
        """
        temp_k1, temp_k2 = _hkdf(self.ck, b"", 2)
        return CipherState(temp_k1), CipherState(temp_k2)
