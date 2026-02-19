"""
CID (Content Identifier) utilities for Bitswap.

This module provides simplified CID encoding/decoding for different Bitswap
protocol versions.
Note: This is a simplified implementation for demonstration. In production,
use a proper CID library like py-cid or multiformats.

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
from typing import Any

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
CIDInput = bytes | str | CIDv0 | CIDv1
CIDObject = CIDv0 | CIDv1


def _compute_multihash_sha256(data: bytes) -> bytes:
    """Compute multihash (SHA2-256) for data."""
    digest = hashlib.sha256(data).digest()
    # Multihash format: <hash-type><hash-length><hash-digest>
    return bytes([int(HASH_SHA256), len(digest)]) + digest


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


def _parse_varint(data: bytes, offset: int = 0) -> tuple[int, int] | None:
    """
    Parse an unsigned varint from data starting at offset.

    Returns:
        (value, length) on success, or None on failure.

    """
    value = 0
    shift = 0
    length = 0

    # Varints for multicodec are at most 10 bytes.
    for i in range(offset, min(len(data), offset + 10)):
        byte = data[i]
        value |= (byte & 0x7F) << shift
        length += 1

        if (byte & 0x80) == 0:
            # MSB clear => last byte of varint
            return value, length

        shift += 7

    return None


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
    Compute a CIDv1 for data using py-cid builders.

    CIDv1 format: <version><codec-varint><multihash>

    .. note:: **Breaking Change - CIDv1 Encoding Format**
        This function now uses varint-encoded multicodec prefixes via `add_prefix()`.
        Previously, CIDv1 used a single-byte codec representation.

        **Compatibility:**
        - Codecs < 128 (e.g., raw=0x55, dag-pb=0x70): Formats are **identical**
          (backward compatible, no migration needed).
        - Codecs >= 128: Formats **differ** (breaking change, requires migration).

        See :func:`detect_cid_encoding_version` and :func:`migrate_legacy_cid`
        for migration utilities.

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
    except Exception:
        return b""

    if cid_obj.version != CID_V1:
        return b""

    return cid_obj.prefix().to_bytes()


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

    try:
        return Prefix.from_bytes(prefix).sum(data).buffer
    except Exception:
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
    except Exception:
        logger.debug("        No valid CID format detected")
        return False

    try:
        recomputed = cid_obj.prefix().sum(data).buffer
    except Exception:
        logger.debug("        Failed to recompute CID from parsed prefix")
        return False

    match = recomputed == cid_obj.buffer
    logger.debug(f"        CID check: {'MATCH' if match else 'MISMATCH'}")
    return match


def parse_cid(value: CIDInput) -> CIDv0 | CIDv1:
    """
    Parse and validate CID input into a py-cid object.

    Accepts CID bytes, canonical CID text/path strings, hex-encoded CID bytes,
    or existing py-cid objects.
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
    except Exception:
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
    except Exception:
        # Preserve previous fallback behavior.
        return DAG_PB.name

    return cid_obj.codec


# ============================================================================
# Migration and Version Encoding Detection Utilities
# ============================================================================


def detect_cid_encoding_format(cid: bytes) -> dict[str, Any]:
    """
    Detect CID encoding format and codec details.

    Returns:
        {
            'version': 0 or 1,
            'codec_value': int,
            'codec_name': str,
            'encoding': 'legacy' or 'varint',
            'needs_migration': bool,
            'is_breaking': bool
        }

    """
    from multicodec import Code

    if len(cid) < 2:
        return {"version": None, "error": "CID too short"}

    version = cid[0]

    if version == 0x12:  # CIDv0 (multihash only)
        return {
            "version": 0,
            "codec_value": 0x70,  # dag-pb
            "codec_name": "dag-pb",
            "encoding": "legacy",
            "needs_migration": False,
            "is_breaking": False,
        }

    if version != 0x01:  # Not CIDv1
        return {"version": version, "error": "Unknown CID version"}

    # Parse codec value from varint
    codec_value = 0
    shift = 0
    codec_length = 0

    for i in range(1, min(len(cid), 11)):  # Max varint is 10 bytes
        byte = cid[i]
        codec_value |= (byte & 0x7F) << shift
        shift += 7
        codec_length += 1

        if (byte & 0x80) == 0:  # Last byte
            break

    # Get codec name
    try:
        codec = Code(codec_value)
        codec_name = str(codec)
    except Exception:
        codec_name = f"0x{codec_value:x}"

    # Determine if this uses legacy or varint encoding
    # Legacy: single byte for all codecs
    # Varint: matches codec_value encoding
    is_breaking = codec_value >= 128

    # For codecs < 128, legacy and varint are identical (both 1 byte)
    # For codecs ≥ 128, we can't definitively tell without the original data
    # But we assume varint if properly implemented
    encoding = "varint" if codec_length > 1 else "legacy-or-varint"

    return {
        "version": 1,
        "codec_value": codec_value,
        "codec_name": codec_name,
        "codec_length": codec_length,
        "encoding": encoding,
        "needs_migration": False,  # Can't migrate without data
        "is_breaking": is_breaking,
    }


def recompute_cid_from_data(old_cid: bytes, data: bytes) -> bytes:
    """
    Recompute CID with proper varint encoding.

    Note: Original data is required because CIDs use cryptographic hashes
    (one-way functions that cannot be reversed).

    Args:
        old_cid: Existing CID (used to extract codec)
        data: Original data that was hashed

    Returns:
        New CID with proper varint-encoded codec

    Raises:
        ValueError: If old_cid is invalid or doesn't match data

    """
    # Detect old CID format
    info = detect_cid_encoding_format(old_cid)

    if info.get("error"):
        raise ValueError(f"Invalid CID: {info['error']}")

    # First, ensure the provided data actually matches the original CID.
    # If this fails, the caller is not supplying the correct original data.
    if not verify_cid(old_cid, data):
        raise ValueError("Recomputed CID does not verify with provided data")

    # Extract codec from the old CID encoding
    codec_value = info["codec_value"]

    # Recompute with proper varint encoding
    new_cid = compute_cid_v1(data, codec=codec_value)

    # Sanity check: new CID must also verify against the same data
    if not verify_cid(new_cid, data):
        raise ValueError("Recomputed CID does not verify with provided data")

    return new_cid


def analyze_cid_collection(cids: list[bytes]) -> dict[str, Any]:
    """
    Analyze a collection of CIDs for migration impact.

    Returns:
        {
            'total': int,
            'backward_compatible': int,
            'breaking_change': int,
            'by_codec': {codec_name: count},
            'breaking_cids': [bytes]
        }

    """
    results: dict[str, Any] = {
        "total": len(cids),
        "backward_compatible": 0,
        "breaking_change": 0,
        "by_codec": {},
        "breaking_cids": [],
    }

    by_codec: dict[str, int] = {}
    breaking_cids: list[bytes] = []

    for cid in cids:
        try:
            info = detect_cid_encoding_format(cid)

            if info.get("error"):
                continue

            codec_name = info["codec_name"]
            by_codec[codec_name] = by_codec.get(codec_name, 0) + 1

            if info["is_breaking"]:
                results["breaking_change"] += 1
                breaking_cids.append(cid)
            else:
                results["backward_compatible"] += 1
        except Exception:
            continue

    results["by_codec"] = by_codec
    results["breaking_cids"] = breaking_cids
    return results
