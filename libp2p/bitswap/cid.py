"""
CID (Content Identifier) utilities for Bitswap.

This module provides py-cid-backed CID encoding/decoding helpers for Bitswap.
Byte-returning functions are preserved for compatibility with existing callers,
and object-returning variants are provided for new code paths.

====================================
IMPORTANT: Breaking Change in v1.0
====================================

CIDv1 now uses proper varint encoding for codec values:

- Codecs < 128: Single byte (backward compatible)
  Example: raw (0x55) → [0x55]

- Codecs ≥ 128: Multi-byte varint (BREAKING CHANGE)
  Example: dag-jose (0x85) → [0x85, 0x01]

This matches the multicodec specification but changes binary format
for dag-jose, dag-json, and experimental codecs.
"""

import hashlib
from typing import TypeAlias

from cid import CIDv0, CIDv1, V0Builder, V1Builder, from_string, make_cid
from cid.prefix import Prefix
from multicodec import Code, is_codec
from multicodec.code_table import DAG_PB, RAW, SHA2_256

# Simplified CID version constants
CID_V0 = 0
CID_V1 = 1

# Multicodec and multihash constants (type-safe Code objects)
CODEC_DAG_PB: Code = DAG_PB
CODEC_RAW: Code = RAW
HASH_SHA256: Code = SHA2_256
CIDInput: TypeAlias = bytes | str | CIDv0 | CIDv1
CIDObject: TypeAlias = CIDv0 | CIDv1


def _normalise_codec(codec: Code | str | int) -> Code:
    """Normalise codec input to a Code object with validation."""
    if isinstance(codec, Code):
        return codec

    if isinstance(codec, str):
        if not is_codec(codec):
            raise ValueError(f"Unknown codec: {codec}")
        return Code.from_string(codec)

    # Integer code path.
    normalised = Code(codec)
    # If the name is unknown, the code is not registered
    if normalised.name in ("<unknown>", "", None):
        raise ValueError(f"Unknown codec code: 0x{codec:x}")
    return normalised


def compute_cid_v0_obj(data: bytes) -> CIDv0:
    """Compute a CIDv0 object for data."""
    return V0Builder().sum(data)


def compute_cid_v0(data: bytes) -> bytes:
    """
    Compute a CIDv0 for data using py-cid builders.

    CIDv0 semantically wraps a SHA2-256 multihash. For compatibility with
    existing Bitswap code, this helper returns the raw CID bytes.

    Args:
        data: The data to hash

    Returns:
        CIDv0 as bytes (multihash format)

    """
    return compute_cid_v0_obj(data).buffer


def compute_cid_v1_obj(data: bytes, codec: Code | str | int = CODEC_RAW) -> CIDv1:
    """Compute a CIDv1 object for data and codec."""
    code_obj = _normalise_codec(codec)
    return V1Builder(codec=str(code_obj), mh_type=str(HASH_SHA256)).sum(data)


def compute_cid_v1(data: bytes, codec: Code | str | int = CODEC_RAW) -> bytes:
    """
    Compute a CIDv1 for data and return raw CID bytes.

    This is the compatibility wrapper over :func:`compute_cid_v1_obj`.

    Args:
        data: The data to hash
        codec: Multicodec code (default: raw). Can be a Code object, string name,
               or integer code.

    Returns:
        CIDv1 as bytes in multicodec format

    Raises:
        ValueError: If codec is invalid or unknown

    """
    return compute_cid_v1_obj(data, codec).buffer


def get_cid_prefix(cid: bytes) -> bytes:
    """
    Extract the CID prefix (everything except the digest).

    For v1.1.0+ Block messages, the prefix includes:
    <version><codec-varint><hash-type><hash-length>
    but not the hash digest.

    Args:
        cid: The CID bytes

    Returns:
        CID prefix bytes, or empty bytes if not applicable/invalid.

    """
    # CIDv0 - no prefix needed for v1.0.0.
    try:
        cid_obj = parse_cid(cid)
    except ValueError:
        return b""

    if cid_obj.version != CID_V1:
        return b""

    return cid_obj.prefix().to_bytes()


def reconstruct_cid_from_prefix_and_data(prefix: bytes, data: bytes) -> bytes:
    """
    Reconstruct a CID from prefix and data using py-cid Prefix APIs.

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

    try:
        return Prefix.from_bytes(prefix).sum(data).buffer
    except ValueError:
        # Preserve previous permissive behavior for malformed prefixes.
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
    try:
        cid_obj = parse_cid(cid)
    except ValueError:
        logger.debug("        No valid CID format detected")
        return False

    try:
        recomputed = cid_obj.prefix().sum(data).buffer
    except ValueError:
        logger.debug("        Failed to recompute CID from parsed prefix")
        return False

    match = recomputed == cid_obj.buffer
    logger.debug(f"        CID check: {'MATCH' if match else 'MISMATCH'}")
    return match


def parse_cid(value: CIDInput) -> CIDv0 | CIDv1:
    """
    Parse and validate CID input into a py-cid object.

    Accepts CID bytes, canonical CID text/path strings, hex-encoded CID bytes,
    or existing py-cid objects. Hex-encoded strings (with or without a leading
    ``0x``) are accepted when canonical CID string parsing fails.
    """
    if isinstance(value, (CIDv0, CIDv1)):
        return value

    if isinstance(value, bytes):
        return make_cid(value)

    if isinstance(value, str):
        cid_str = value.strip()
        if not cid_str:
            raise ValueError("CID string is empty")

        try:
            return from_string(cid_str)
        except ValueError:
            hex_value = cid_str[2:] if cid_str.lower().startswith("0x") else cid_str
            try:
                return make_cid(bytes.fromhex(hex_value))
            except ValueError as exc:
                raise ValueError(f"Invalid CID string: {cid_str}") from exc

    raise TypeError(f"Unsupported CID input type: {type(value).__name__}")


def cid_to_bytes(value: CIDInput) -> bytes:
    """Convert CID input to raw CID bytes."""
    return parse_cid(value).buffer


def cid_to_text(value: CIDInput) -> str:
    """Convert CID input to canonical CID string form."""
    return str(parse_cid(value))


def format_cid_for_display(cid: bytes, max_len: int | None = None) -> str:
    """Return CID text for display, with hex fallback and optional truncation."""
    try:
        result = cid_to_text(cid)
    except (TypeError, ValueError):
        result = cid.hex()

    if max_len is not None and len(result) > max_len:
        return f"{result[:max_len]}..."
    return result


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

    try:
        return parse_cid(cid).version
    except ValueError:
        # Preserve previous behavior for malformed CIDs.
        if cid[0] == CID_V1:
            return CID_V1
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


def compute_cid_obj(
    data: bytes, version: int = CID_V0, codec: Code | str | int = CODEC_RAW
) -> CIDObject:
    """Compute a CID object for data with specified version."""
    if version == CID_V0:
        return compute_cid_v0_obj(data)
    return compute_cid_v1_obj(data, codec)


def parse_cid_codec(cid: bytes) -> str:
    """
    Extract the codec name from a CID.

    For CIDv0 (no explicit codec), returns ``dag-pb`` (the implicit codec).
    """
    try:
        cid_obj = parse_cid(cid)
    except ValueError:
        # Preserve previous fallback behavior.
        return DAG_PB.name

    return cid_obj.codec
