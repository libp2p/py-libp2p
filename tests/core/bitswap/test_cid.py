"""Unit tests for CID computation and verification."""

import hashlib

import pytest
from cid import make_cid

from libp2p.bitswap.cid import (
    CODEC_DAG_PB,
    CODEC_RAW,
    cid_to_bytes,
    cid_to_text,
    compute_cid_obj,
    compute_cid_v0,
    compute_cid_v0_obj,
    compute_cid_v1,
    compute_cid_v1_obj,
    get_cid_prefix,
    parse_cid,
    verify_cid,
)


class TestComputeCID:
    """Test CID computation."""

    def test_compute_cid_simple(self):
        """Test computing CID for simple data."""
        data = b"Hello, World!"
        cid = compute_cid_v1(data)

        # CID should be bytes
        assert isinstance(cid, bytes)
        # Should have reasonable length (>0)
        assert len(cid) > 0

    def test_compute_cid_empty(self):
        """Test computing CID for empty data."""
        data = b""
        cid = compute_cid_v1(data)

        assert isinstance(cid, bytes)
        assert len(cid) > 0

    def test_compute_cid_large_data(self):
        """Test computing CID for large data."""
        data = b"x" * 1024 * 1024  # 1MB
        cid = compute_cid_v1(data)

        assert isinstance(cid, bytes)
        assert len(cid) > 0

    def test_compute_cid_deterministic(self):
        """Test that CID computation is deterministic."""
        data = b"test data"
        cid1 = compute_cid_v1(data)
        cid2 = compute_cid_v1(data)

        assert cid1 == cid2

    def test_compute_cid_different_data(self):
        """Test that different data produces different CIDs."""
        data1 = b"data1"
        data2 = b"data2"

        cid1 = compute_cid_v1(data1)
        cid2 = compute_cid_v1(data2)

        assert cid1 != cid2

    def test_compute_cid_raw_codec(self):
        """Test computing CID with raw codec."""
        data = b"raw data"
        cid = compute_cid_v1(data, codec=CODEC_RAW)

        assert isinstance(cid, bytes)
        assert len(cid) > 0

    def test_compute_cid_dag_pb_codec(self):
        """Test computing CID with DAG-PB codec."""
        data = b"dag-pb data"
        cid = compute_cid_v1(data, codec=CODEC_DAG_PB)

        assert isinstance(cid, bytes)
        assert len(cid) > 0

    def test_compute_cid_codec_difference(self):
        """Test that different codecs produce different CIDs for same data."""
        data = b"test data"
        cid_raw = compute_cid_v1(data, codec=CODEC_RAW)
        cid_dag_pb = compute_cid_v1(data, codec=CODEC_DAG_PB)

        assert cid_raw != cid_dag_pb

    def test_string_codec_equivalence(self):
        """Using codec as string or Code should yield same CID."""
        data = b"codec string vs Code"
        cid1 = compute_cid_v1(data, "raw")
        cid2 = compute_cid_v1(data, CODEC_RAW)

        assert cid1 == cid2

    def test_invalid_codec_inputs(self):
        """Invalid codec names or codes should raise ValueError."""
        data = b"invalid codec test"

        with pytest.raises(ValueError):
            compute_cid_v1(data, "nonexistent-codec")

        with pytest.raises(ValueError):
            compute_cid_v1(data, 0xFFFFFFFF)

    def test_multibyte_varint_codec(self):
        """Test codecs with multi-byte varint encoding (code > 127)."""
        # blake2b-8 has code 0xb201, so add_prefix produces a multi-byte varint
        data = b"multibyte codec test"
        cid = compute_cid_v1(data, codec="blake2b-8")

        assert isinstance(cid, bytes)
        assert len(cid) > 0
        # CIDv1: version(1) + codec-varint(2+ bytes for 0xb201) + multihash
        assert cid[0] == 0x01
        # Second byte should be part of varint (not a single-byte codec like 0x55)
        assert verify_cid(cid, data) is True


class TestVerifyCID:
    """Test CID verification."""

    def test_verify_valid_cid(self):
        """Test verifying a valid CID."""
        data = b"test data"
        cid = compute_cid_v1(data)

        assert verify_cid(cid, data) is True

    def test_verify_invalid_data(self):
        """Test verifying CID with wrong data."""
        data1 = b"correct data"
        data2 = b"wrong data"
        cid = compute_cid_v1(data1)

        assert verify_cid(cid, data2) is False

    def test_verify_empty_data(self):
        """Test verifying CID for empty data."""
        data = b""
        cid = compute_cid_v1(data)

        assert verify_cid(cid, data) is True

    def test_verify_large_data(self):
        """Test verifying CID for large data."""
        data = b"y" * 1024 * 1024  # 1MB
        cid = compute_cid_v1(data)

        assert verify_cid(cid, data) is True

    def test_verify_invalid_cid_format(self):
        """Test verifying with invalid CID format."""
        data = b"test data"
        invalid_cid = b"not-a-valid-cid"

        # Should handle gracefully and return False
        result = verify_cid(invalid_cid, data)
        assert result is False

    def test_old_cid_format_decoding(self):
        """
        Verify that a CID built with the legacy single-byte codec layout still verifies.

        Layout: <version=0x01><codec=0x55><hash-type=0x12><hash-length=0x20><digest>
        """
        data = b"backward compatible data"
        digest = hashlib.sha256(data).digest()

        # 0x01 = CIDv1, 0x55 = raw, 0x12 = sha2-256, 0x20 = 32-byte digest
        old_cid = bytes([0x01, 0x55, 0x12, len(digest)]) + digest

        assert verify_cid(old_cid, data) is True


def test_get_cid_prefix_multibyte_varint():
    """Test prefix extraction with 2-byte varint codec."""
    # dag-jose (0x85 = 133) uses varint: 0x85 0x01
    data = b"test data"
    cid = compute_cid_v1(data, codec=0x85)

    prefix = get_cid_prefix(cid)

    # Should be: version(1) + codec(2) + hash_type(1) + hash_len(1) = 5 bytes
    assert len(prefix) == 5, f"Expected 5, got {len(prefix)}"
    assert prefix[0] == 0x01  # CIDv1
    assert prefix[1:3] == bytes([0x85, 0x01])  # 2-byte varint


def test_verify_cid_multibyte_varint():
    """Test verification with 2-byte varint codec."""
    data = b"test data"
    cid = compute_cid_v1(data, codec=0x85)  # dag-jose

    # Should verify successfully
    assert verify_cid(cid, data) is True

    # Should fail with wrong data
    assert verify_cid(cid, b"wrong data") is False


def test_backward_compatible_codecs():
    """Verify codecs < 128 are backward compatible."""
    test_data = b"Hello World"

    # Test raw (0x55)
    cid_raw = compute_cid_v1(test_data, codec=0x55)
    assert cid_raw[1] == 0x55  # Single byte

    # Test dag-pb (0x70)
    cid_dag_pb = compute_cid_v1(test_data, codec=0x70)
    assert cid_dag_pb[1] == 0x70  # Single byte

    # Test dag-cbor (0x71)
    cid_dag_cbor = compute_cid_v1(test_data, codec=0x71)
    assert cid_dag_cbor[1] == 0x71  # Single byte

    # Verify prefix extraction works
    for cid in [cid_raw, cid_dag_pb, cid_dag_cbor]:
        prefix = get_cid_prefix(cid)
        # version(1) + codec(1-byte varint) + hash_type(1) + hash_len(1)
        assert len(prefix) == 4
        assert verify_cid(cid, test_data) is True


def test_multibyte_varint_codecs():
    """Verify codecs ≥ 128 use multi-byte varint encoding."""
    test_data = b"test data"

    # Test dag-jose (0x85 = 133)
    cid_dag_json = compute_cid_v1(test_data, codec=0x85)

    # Should use 2-byte varint: 0x85 0x01
    assert cid_dag_json[1:3] == bytes([0x85, 0x01])

    # Prefix should be 5 bytes: version(1) + codec(2) + type(1) + len(1)
    prefix = get_cid_prefix(cid_dag_json)
    assert len(prefix) == 5, f"Expected 5, got {len(prefix)}"

    # Verification should work
    assert verify_cid(cid_dag_json, test_data) is True

    # Test dag-json (0x0129 = 297) if available
    try:
        cid_dag_jose = compute_cid_v1(test_data, codec=0x0129)
        assert (
            len(get_cid_prefix(cid_dag_jose)) == 5
        )  # version(1) + codec(2) + type(1) + len(1)
        assert verify_cid(cid_dag_jose, test_data) is True
    except ValueError:
        # Codec not available in this multicodec table
        pass


def test_cid_edge_cases():
    """Test edge cases and error handling."""
    # Test empty data
    cid_empty = compute_cid_v1(b"", codec=0x55)
    assert verify_cid(cid_empty, b"") is True

    # Test large data
    large_data = b"x" * 10000
    cid_large = compute_cid_v1(large_data, codec=0x55)
    assert verify_cid(cid_large, large_data) is True

    # Test invalid CID (too short)
    assert get_cid_prefix(b"\x01") == b""
    assert verify_cid(b"\x01", b"test") is False

    # Test string codec input
    cid_str = compute_cid_v1(b"test", codec="raw")
    cid_int = compute_cid_v1(b"test", codec=0x55)
    assert cid_str == cid_int

    # Test invalid codec
    with pytest.raises(ValueError) as excinfo:
        compute_cid_v1(b"test", codec="nonexistent")
    assert "Unknown codec" in str(excinfo.value)


def test_complete_cid_workflow():
    """End-to-end test of CID creation, parsing, and verification."""
    test_data = b"Integration test data"
    test_codecs = [
        (0x55, "raw", False),  # Backward compatible
        (0x70, "dag-pb", False),  # Backward compatible
        (0x85, "dag-jose", True),  # Breaking (code 0x85)
        (0x129, "dag-json", True),  # Breaking (code 0x129)
    ]

    for codec_value, _, is_breaking in test_codecs:
        # Create CID
        cid = compute_cid_v1(test_data, codec=codec_value)

        # Extract prefix
        prefix = get_cid_prefix(cid)
        expected_prefix_len = 5 if is_breaking else 4
        assert len(prefix) == expected_prefix_len

        # Verify CID
        assert verify_cid(cid, test_data) is True
        assert verify_cid(cid, b"wrong data") is False


def test_parse_cid_accepts_bytes_and_objects():
    """parse_cid should normalize bytes and py-cid objects."""
    cid_bytes = compute_cid_v1(b"helper-bytes")

    parsed_from_bytes = parse_cid(cid_bytes)
    parsed_from_obj = parse_cid(parsed_from_bytes)

    assert parsed_from_bytes.buffer == cid_bytes
    assert parsed_from_obj.buffer == cid_bytes


def test_parse_cid_accepts_canonical_and_hex_strings():
    """parse_cid should accept both canonical CID text and legacy hex text."""
    cid_bytes = compute_cid_v1(b"helper-strings")
    canonical = str(make_cid(cid_bytes))
    hex_text = cid_bytes.hex()

    parsed_from_canonical = parse_cid(canonical)
    parsed_from_hex = parse_cid(hex_text)

    assert parsed_from_canonical.buffer == cid_bytes
    assert parsed_from_hex.buffer == cid_bytes


def test_parse_cid_invalid_inputs_raise():
    """parse_cid should raise on unsupported or malformed input."""
    with pytest.raises(TypeError):
        parse_cid(123)  # type: ignore[arg-type]

    with pytest.raises(ValueError):
        parse_cid("")

    with pytest.raises(ValueError):
        parse_cid("not-a-valid-cid")


def test_cid_to_bytes_and_text_roundtrip():
    """Helper conversion functions should round-trip consistently."""
    cid_bytes = compute_cid_v1(b"helper-roundtrip")
    cid_text = cid_to_text(cid_bytes)
    roundtrip_bytes = cid_to_bytes(cid_text)

    assert roundtrip_bytes == cid_bytes
    assert cid_text == str(make_cid(cid_bytes))


def test_object_wrappers_for_v0_and_v1():
    """Object-returning wrappers should match bytes-returning wrappers."""
    data = b"object-wrapper-test"

    cid_v0_obj = compute_cid_v0_obj(data)
    cid_v1_obj = compute_cid_v1_obj(data, codec=CODEC_RAW)

    assert cid_v0_obj.buffer == compute_cid_v0(data)
    assert cid_v1_obj.buffer == compute_cid_v1(data, codec=CODEC_RAW)
    assert cid_v0_obj.version == 0
    assert cid_v1_obj.version == 1


def test_compute_cid_obj_wrapper():
    """compute_cid_obj should mirror compute_cid by version."""
    data = b"generic-object-wrapper-test"

    cid0_obj = compute_cid_obj(data, version=0)
    cid1_obj = compute_cid_obj(data, version=1, codec=CODEC_DAG_PB)

    assert cid0_obj.buffer == compute_cid_v0(data)
    assert cid1_obj.buffer == compute_cid_v1(data, codec=CODEC_DAG_PB)
    assert cid0_obj.version == 0
    assert cid1_obj.version == 1
