"""Unit tests for CID computation and verification."""

from libp2p.bitswap.cid import (
    CODEC_DAG_PB,
    CODEC_RAW,
    compute_cid_v1,
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
