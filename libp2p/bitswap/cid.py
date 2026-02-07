"""
CID (Content Identifier) utilities for Bitswap.

This module provides simplified CID encoding/decoding for different Bitswap
protocol versions.
Note: This is a simplified implementation for demonstration. In production,
use a proper CID library like py-cid or multiformats.
"""

import hashlib

from multicodec import Code, add_prefix, get_codec, is_codec
from multicodec.code_table import DAG_PB, RAW, SHA2_256

# Simplified CID version constants
CID_V0 = 0
CID_V1 = 1

# Multicodec and multihash constants (type-safe Code objects)
CODEC_DAG_PB: Code = DAG_PB
CODEC_RAW: Code = RAW
HASH_SHA256: Code = SHA2_256


def _compute_multihash_sha256(data: bytes) -> bytes:
    """Compute multihash (SHA2-256) for data."""
    digest = hashlib.sha256(data).digest()
    # Multihash format: <hash-type><hash-length><hash-digest>
    return bytes([int(HASH_SHA256), len(digest)]) + digest


def compute_cid_v0(data: bytes) -> bytes:
    """
    Compute a CIDv0 for data using py-multihash v3 API.

    CIDv0 is just a base58-encoded multihash (SHA-256).
    For simplicity, we return the raw multihash bytes.

    Args:
        data: The data to hash

    Returns:
        CIDv0 as bytes (multihash format)

    """
    # CIDv0 is just the multihash
    return _compute_multihash_sha256(data)


def _normalise_codec(codec: Code | str | int) -> Code:
    """Normalise codec input to a Code object with validation."""
    if isinstance(codec, Code):
        return codec

    if isinstance(codec, str):
        if not is_codec(codec):
            raise ValueError(f"Unknown codec: {codec}")
        return Code.from_string(codec)

    # Integer code path
    normalised = Code(codec)
    # If the name is unknown, the code is not registered
    if normalised.name in ("<unknown>", "", None):
        raise ValueError(f"Unknown codec code: 0x{codec:x}")
    return normalised


def compute_cid_v1(data: bytes, codec: Code | str | int = CODEC_RAW) -> bytes:
    """
    Compute a CIDv1 for data using py-multihash v3 API.

    CIDv1 format: <version><codec><multihash>

    Args:
        data: The data to hash
        codec: Multicodec code (default: raw)

    Returns:
        CIDv1 as bytes

    """
    # Normalise codec and compute multihash
    code_obj = _normalise_codec(codec)
    multihash = _compute_multihash_sha256(data)

    # Use multicodec to get the properly varint-encoded codec prefix.
    # add_prefix returns <codec-varint><data>; we only need the prefix bytes.
    codec_prefixed = add_prefix(str(code_obj), b"")

    # CIDv1 format: <version><codec-varint><multihash>
    return bytes([CID_V1]) + codec_prefixed + multihash


def get_cid_prefix(cid: bytes) -> bytes:
    """
    Extract the CID prefix (everything except the digest).

    For v1.1.0 Block messages, the prefix includes version, codec, and
    multihash type/length, but not the hash digest.

    Args:
        cid: The CID bytes

    Returns:
        CID prefix bytes

    """
    if len(cid) < 2:
        # CIDv0 - no prefix needed for v1.0.0
        return b""

    # Check if CIDv1 (starts with 0x01)
    if cid[0] == CID_V1:
        # For CIDv1 produced by this module, the structure is:
        # <version><codec-varint><hash-type><hash-length><digest>
        #
        # We don't parse the varint here; instead, we preserve the prefix
        # up to (but not including) the digest, which is everything except
        # the last `hash_length` bytes.
        if len(cid) >= 4:
            hash_length = cid[-1]
            prefix_len = len(cid) - hash_length
            return cid[:prefix_len]

    # For CIDv0 or unknown, return empty prefix
    return b""


def reconstruct_cid_from_prefix_and_data(prefix: bytes, data: bytes) -> bytes:
    """
    Reconstruct a CID from prefix and data using py-multihash v3 API.

    Used when receiving v1.1.0+ Block messages with prefix.

    Args:
        prefix: CID prefix (version, codec, hash type, hash length)
        data: Block data

    Returns:
        Full CID bytes

    """
    if not prefix:
        # No prefix means CIDv0
        return compute_cid_v0(data)

    # Compute hash digest and recompute full CID by delegating to verify_cid logic.
    # The prefix already contains version, codec-varint, hash-type and hash-length.
    digest = hashlib.sha256(data).digest()
    return prefix + digest


def verify_cid(cid: bytes, data: bytes) -> bool:
    """
    Verify that data matches the given CID.

    Args:
        cid: The CID to verify against
        data: The data to verify

    Returns:
        True if data matches CID, False otherwise

    """
    import logging

    logger = logging.getLogger(__name__)

    logger.debug("      verify_cid:")
    logger.debug(f"        CID: {cid.hex()}")
    logger.debug(f"        Data size: {len(data)} bytes")

    # For CIDv0 (multihash)
    if len(cid) >= 2 and cid[0] == int(HASH_SHA256):
        # Extract digest from multihash
        hash_length = cid[1]
        if len(cid) >= 2 + hash_length:
            cid_digest = cid[2 : 2 + hash_length]
            match = digest == cid_digest
            logger.debug(f"        CIDv0 check: {'MATCH' if match else 'MISMATCH'}")
            logger.debug(f"        Expected digest: {cid_digest.hex()}")
            return match

    # For CIDv1
    if len(cid) >= 4 and cid[0] == CID_V1:
        # Extract digest from CIDv1 produced by this module:
        # <version><codec-varint><hash-type><hash-length><digest>
        # We know the hash type and length are the last two header bytes
        hash_type = cid[-(1 + 1 + len(digest))]
        hash_length = cid[-(1 + len(digest))]
        logger.debug(f"        CIDv1: hash_type={hex(hash_type)}, length={hash_length}")
        if hash_type == int(HASH_SHA256) and hash_length == len(digest):
            cid_digest = cid[-len(digest) :]
            match = digest == cid_digest
            logger.debug(f"        CIDv1 check: {'MATCH' if match else 'MISMATCH'}")
            logger.debug(f"        Expected digest: {cid_digest.hex()}")
            logger.debug(f"        Computed digest: {digest.hex()}")
            return match

    logger.debug("        No valid CID format detected")
    return False


def cid_to_string(cid: bytes) -> str:
    """
    Convert CID bytes to a readable hex string.

    Args:
        cid: The CID bytes

    Returns:
        Hex string representation

    """
    return cid.hex()


def parse_cid_version(cid: bytes) -> int:
    """
    Determine the CID version.

    Args:
        cid: The CID bytes

    Returns:
        CID version (0 or 1)

    """
    if len(cid) < 1:
        return CID_V0

    if cid[0] == CID_V1:
        return CID_V1

    # Default to v0 (multihash)
    return CID_V0


def compute_cid(
    data: bytes, version: int = CID_V0, codec: Code | str | int = CODEC_RAW
) -> bytes:
    """
    Compute a CID for data with specified version.

    Args:
        data: The data to hash
        version: CID version (0 or 1)
        codec: Multicodec code (for v1 only)

    Returns:
        CID bytes

    """
    if version == CID_V0:
        return compute_cid_v0(data)
    else:
        return compute_cid_v1(data, codec)


def parse_cid_codec(cid: bytes) -> str:
    """
    Extract the codec name from a CID.

    For CIDv0, there is no explicit codec, and callers should treat this
    as the legacy dag-pb form used by IPFS (often reported as "cidv0").
    For CIDv1, this uses multicodec's `get_codec` helper.
    """
    if len(cid) < 2 or cid[0] != CID_V1:
        # CIDv0 - codec is implicit (typically dag-pb), we return a sentinel.
        return "cidv0"

    # Skip version byte and let multicodec parse the leading codec varint.
    codec_prefixed = cid[1:]
    return get_codec(codec_prefixed)
