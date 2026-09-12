"""
X-Wing combining function shared across KEM backends.

Single source of truth for the X-Wing domain separation label and the
SHA3-256 combiner used by both XWingKem (kyber-py) and LibOQSXWingKem.
"""

import hashlib

# X-Wing domain separation label: ASCII bytes for "\.//^\"
_XWING_LABEL = bytes([0x5C, 0x2E, 0x2F, 0x2F, 0x5E, 0x5C])


def _xwing_combine(
    ss_mlkem: bytes,
    ss_x25519: bytes,
    ct_x25519: bytes,
    pk_x25519: bytes,
) -> bytes:
    r"""
    Combine ML-KEM and X25519 shared secrets per @noble/post-quantum 0.6.0.

    SHA3-256(ss_mlkem || ss_x25519 || ct_x25519 || pk_x25519 || label)
    where label = b'\\.//' + b'^\\' (6 bytes, domain separation).

    Note: label is appended LAST to match @noble/post-quantum 0.6.0 combiner:
    sha3_256(concatBytes(ss[0], ss[1], ct[1], pk[1], asciiToBytes('\\.//^\\')))
    """
    return hashlib.sha3_256(
        ss_mlkem + ss_x25519 + ct_x25519 + pk_x25519 + _XWING_LABEL
    ).digest()
