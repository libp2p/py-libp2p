"""Unit tests for CID computation and verification."""

import time

import pytest

from libp2p.bitswap.cid import (
    CODEC_DAG_PB,
    CODEC_RAW,
    compute_cid_v0,
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


class TestCompatibility:
    """Test compatibility with py-multihash v3 and edge cases."""

    def test_malformed_multihash_handling(self):
        """Test handling of malformed multihash in CID."""
        data = b"test data"

        # Malformed multihash: invalid length field
        malformed_cid = bytes([0x12, 0xFF, 0x00])  # SHA-256 code, invalid length

        # Should handle gracefully and return False
        assert verify_cid(malformed_cid, data) is False

    def test_truncated_cid_handling(self):
        """Test handling of truncated CID."""
        data = b"test data"

        # Truncated CIDv1: too short to be valid
        truncated_cid = bytes([0x01, 0x55])  # Only version and codec, no multihash

        # Should handle gracefully and return False
        assert verify_cid(truncated_cid, data) is False

    def test_empty_cid_handling(self):
        """Test handling of empty CID."""
        data = b"test data"
        empty_cid = b""

        # Should handle gracefully and return False
        assert verify_cid(empty_cid, data) is False

    def test_single_byte_cid_handling(self):
        """Test handling of single-byte CID."""
        data = b"test data"
        single_byte_cid = bytes([0x12])  # Only hash type, no length or digest

        # Should handle gracefully and return False
        assert verify_cid(single_byte_cid, data) is False

    def test_cid_with_wrong_hash_type(self):
        """Test CID with unsupported hash type."""
        data = b"test data"

        # Create CID with unsupported hash type (0xFF)
        wrong_hash_cid = bytes([0x01, 0x55, 0xFF, 0x20]) + b"\x00" * 32

        # Should handle gracefully and return False
        assert verify_cid(wrong_hash_cid, data) is False

    def test_cidv0_format_compatibility(self):
        """Test CIDv0 format (raw multihash) compatibility."""
        data = b"hello world"

        # Compute CIDv0 (which is just a multihash)
        cid_v0 = compute_cid_v0(data)

        # Verify it works
        assert verify_cid(cid_v0, data) is True

        # Verify with wrong data fails
        assert verify_cid(cid_v0, b"wrong data") is False

    def test_cidv1_format_compatibility(self):
        """Test CIDv1 format compatibility."""
        data = b"hello world"

        # Compute CIDv1
        cid_v1 = compute_cid_v1(data, codec=CODEC_RAW)

        # Verify it works
        assert verify_cid(cid_v1, data) is True

        # Verify with wrong data fails
        assert verify_cid(cid_v1, b"wrong data") is False


@pytest.mark.benchmark
class TestPerformance:
    """Performance benchmarks for py-multihash v3 integration."""

    def test_cid_computation_performance(self):
        """Benchmark CID computation speed."""
        # Test with 1MB of data
        data = b"x" * (1024 * 1024)
        iterations = 10

        # Warm up
        for _ in range(2):
            compute_cid_v1(data)

        # Benchmark
        start = time.perf_counter()
        for _ in range(iterations):
            compute_cid_v1(data)
        elapsed = time.perf_counter() - start

        avg_time = elapsed / iterations

        # Should complete 10 iterations of 1MB in reasonable time
        # Expected: < 0.5 seconds total (< 50ms per iteration)
        assert elapsed < 2.0, (
            f"CID computation too slow: {elapsed:.3f}s for {iterations} iterations"
        )

        # Log performance for reference
        print(
            f"\nCID computation: {avg_time * 1000:.2f}ms per 1MB "
            f"(total: {elapsed:.3f}s for {iterations} iterations)"
        )

    def test_verification_performance(self):
        """Benchmark CID verification speed."""
        # Test with 1MB of data
        data = b"x" * (1024 * 1024)
        cid = compute_cid_v1(data)
        iterations = 10

        # Warm up
        for _ in range(2):
            verify_cid(cid, data)

        # Benchmark
        start = time.perf_counter()
        for _ in range(iterations):
            verify_cid(cid, data)
        elapsed = time.perf_counter() - start

        avg_time = elapsed / iterations

        # Should complete 10 iterations of 1MB verification in reasonable time
        # Expected: < 0.5 seconds total (< 50ms per iteration)
        assert elapsed < 2.0, (
            f"CID verification too slow: {elapsed:.3f}s for {iterations} iterations"
        )

        # Log performance for reference
        print(
            f"\nCID verification: {avg_time * 1000:.2f}ms per 1MB "
            f"(total: {elapsed:.3f}s for {iterations} iterations)"
        )

    def test_small_data_performance(self):
        """Benchmark performance with small data (typical use case)."""
        # Test with small data (1KB)
        data = b"x" * 1024
        iterations = 1000

        # Warm up
        for _ in range(10):
            cid = compute_cid_v1(data)
            verify_cid(cid, data)

        # Benchmark computation
        start = time.perf_counter()
        for _ in range(iterations):
            compute_cid_v1(data)
        comp_elapsed = time.perf_counter() - start

        # Benchmark verification
        cid = compute_cid_v1(data)
        start = time.perf_counter()
        for _ in range(iterations):
            verify_cid(cid, data)
        verify_elapsed = time.perf_counter() - start

        # Should handle 1000 iterations of 1KB quickly
        # Expected: < 0.2 seconds for computation, < 0.2 seconds for verification
        assert comp_elapsed < 1.0, (
            f"Small data computation too slow: {comp_elapsed:.3f}s"
        )
        assert verify_elapsed < 1.0, (
            f"Small data verification too slow: {verify_elapsed:.3f}s"
        )

        # Log performance for reference
        comp_ms = comp_elapsed * 1000 / iterations
        verify_ms = verify_elapsed * 1000 / iterations
        print(f"\nSmall data (1KB) - Computation: {comp_ms:.3f}ms per op")
        print(f"Small data (1KB) - Verification: {verify_ms:.3f}ms per op")

    def test_codec_performance(self):
        """Benchmark performance with different codecs."""
        data = b"test data" * 100  # ~1KB
        iterations = 500

        # Benchmark RAW codec
        start = time.perf_counter()
        for _ in range(iterations):
            compute_cid_v1(data, codec=CODEC_RAW)
        raw_elapsed = time.perf_counter() - start

        # Benchmark DAG-PB codec
        start = time.perf_counter()
        for _ in range(iterations):
            compute_cid_v1(data, codec=CODEC_DAG_PB)
        dagpb_elapsed = time.perf_counter() - start

        # Both should be fast and similar (codec doesn't affect hash computation)
        assert raw_elapsed < 1.0, f"RAW codec too slow: {raw_elapsed:.3f}s"
        assert dagpb_elapsed < 1.0, f"DAG-PB codec too slow: {dagpb_elapsed:.3f}s"

        # Log performance for reference
        print("\nCodec performance (500 iterations):")
        print(f"  RAW codec: {raw_elapsed * 1000:.2f}ms")
        print(f"  DAG-PB codec: {dagpb_elapsed * 1000:.2f}ms")
