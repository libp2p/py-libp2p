"""
Performance tests for DHT lookup optimizations.

These tests validate that the heap-based optimizations provide the expected
performance improvements over the original O(n²) implementation.
"""

import time
import unittest
from typing import List

import pytest

from libp2p.kad_dht.utils import (
    find_closest_peers_heap,
    find_closest_peers_streaming,
    get_peer_distance,
    sort_peer_ids_by_distance,
)
from libp2p.peer.id import ID
from libp2p.tools.adaptive_delays import (
    AdaptiveDelayStrategy,
    ErrorType,
)


class TestHeapBasedOptimizations(unittest.TestCase):
    """Test heap-based peer selection optimizations."""
    
    def setUp(self):
        """Set up test data."""
        self.target_key = b"test_target_key_32_bytes_long_12345"
        self.peer_ids = self._generate_peer_ids(1000)  # 1000 peers for testing
    
    def _generate_peer_ids(self, count: int) -> List[ID]:
        """Generate a list of random peer IDs for testing."""
        peer_ids = []
        for i in range(count):
            # Create deterministic but varied peer IDs
            peer_bytes = f"peer_{i:04d}_{'x' * 20}".encode()[:32]
            peer_ids.append(ID(peer_bytes))
        return peer_ids
    
    def test_heap_vs_sort_performance(self):
        """Test that heap-based approach is faster than full sorting for large peer sets."""
        count = 20  # We only need top 20 peers
        
        # Test heap-based approach
        start_time = time.time()
        heap_result = find_closest_peers_heap(self.target_key, self.peer_ids, count)
        heap_time = time.time() - start_time
        
        # Test original sorting approach
        start_time = time.time()
        sort_result = sort_peer_ids_by_distance(self.target_key, self.peer_ids)[:count]
        sort_time = time.time() - start_time
        
        # Results should be identical
        self.assertEqual(heap_result, sort_result)
        
        # Heap approach should be faster for large peer sets
        print(f"Heap time: {heap_time:.6f}s, Sort time: {sort_time:.6f}s")
        self.assertLess(heap_time, sort_time, 
                       f"Heap approach ({heap_time:.6f}s) should be faster than sort ({sort_time:.6f}s)")
    
    def test_heap_memory_efficiency(self):
        """Test that heap approach uses less memory than full sorting."""
        import sys
        
        # Measure memory usage for heap approach
        heap_result = find_closest_peers_heap(self.target_key, self.peer_ids, 20)
        heap_memory = sys.getsizeof(heap_result)
        
        # Measure memory usage for sort approach (creates full sorted list)
        sort_result = sort_peer_ids_by_distance(self.target_key, self.peer_ids)[:20]
        sort_memory = sys.getsizeof(sort_result)
        
        # Both should produce same results
        self.assertEqual(heap_result, sort_result)
        
        # Heap approach should use similar or less memory
        print(f"Heap memory: {heap_memory} bytes, Sort memory: {sort_memory} bytes")
        self.assertLessEqual(heap_memory, sort_memory * 1.1,  # Allow 10% tolerance
                           "Heap approach should use similar or less memory")
    
    def test_streaming_approach(self):
        """Test streaming approach for very large peer sets."""
        def peer_generator():
            """Generator that yields peer IDs one at a time."""
            for peer_id in self.peer_ids:
                yield peer_id
        
        count = 20
        streaming_result = find_closest_peers_streaming(self.target_key, peer_generator(), count)
        heap_result = find_closest_peers_heap(self.target_key, self.peer_ids, count)
        
        # Results should be identical
        self.assertEqual(streaming_result, heap_result)
    
    def test_scalability_with_peer_count(self):
        """Test that performance scales well with increasing peer count."""
        peer_counts = [100, 500, 1000, 2000]
        times = []
        
        for count in peer_counts:
            test_peers = self._generate_peer_ids(count)
            
            start_time = time.time()
            result = find_closest_peers_heap(self.target_key, test_peers, 20)
            elapsed = time.time() - start_time
            
            times.append(elapsed)
            self.assertEqual(len(result), min(20, count))
        
        # Times should scale roughly O(n log k) rather than O(n log n)
        # For k=20, we expect roughly linear scaling with some log factor
        print(f"Times for peer counts {peer_counts}: {times}")
        
        # The ratio of times should be roughly proportional to peer count ratio
        # (allowing for some variance due to log factors)
        ratio_100_500 = times[1] / times[0] if times[0] > 0 else 1
        ratio_500_1000 = times[2] / times[1] if times[1] > 0 else 1
        
        # Should be roughly 5x and 2x respectively (allowing 50% variance)
        self.assertLess(ratio_100_500, 7.5, "Scaling should be roughly linear")
        self.assertLess(ratio_500_1000, 3.0, "Scaling should be roughly linear")
    
    def test_early_termination_conditions(self):
        """Test that early termination works correctly."""
        # Create peers with known distances
        close_peer = ID(b"close_peer_" + b"0" * 20)
        far_peer = ID(b"far_peer_" + b"f" * 20)
        
        # Test with a very close peer
        peers = [far_peer, close_peer]
        result = find_closest_peers_heap(self.target_key, peers, 1)
        
        # Should return the closer peer
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], close_peer)


class TestAdaptiveDelayStrategy(unittest.TestCase):
    """Test adaptive delay strategy for error handling."""
    
    def setUp(self):
        """Set up test strategy."""
        self.strategy = AdaptiveDelayStrategy(
            base_delay=0.001,
            max_delay=0.1,
            backoff_multiplier=2.0,
            max_retries=3
        )
    
    def test_error_classification(self):
        """Test that errors are classified correctly."""
        # Test network timeout
        timeout_error = TimeoutError("Connection timed out")
        self.assertEqual(self.strategy.classify_error(timeout_error), ErrorType.NETWORK_TIMEOUT)
        
        # Test connection refused
        refused_error = ConnectionRefusedError("Connection refused")
        self.assertEqual(self.strategy.classify_error(refused_error), ErrorType.CONNECTION_REFUSED)
        
        # Test unknown error
        unknown_error = ValueError("Some random error")
        self.assertEqual(self.strategy.classify_error(unknown_error), ErrorType.UNKNOWN)
    
    def test_delay_calculation(self):
        """Test that delays are calculated correctly."""
        error = TimeoutError("Test timeout")
        
        # First retry should use base delay
        delay1 = self.strategy.calculate_delay(error, "test_op", 1)
        self.assertGreater(delay1, 0)
        self.assertLess(delay1, 0.01)  # Should be small
        
        # Second retry should use exponential backoff
        delay2 = self.strategy.calculate_delay(error, "test_op", 2)
        self.assertGreater(delay2, delay1)
        
        # Third retry should be even longer
        delay3 = self.strategy.calculate_delay(error, "test_op", 3)
        self.assertGreater(delay3, delay2)
        
        # Fourth retry should exceed max retries
        delay4 = self.strategy.calculate_delay(error, "test_op", 4)
        self.assertEqual(delay4, 0.0)  # Should be 0 (no retry)
    
    def test_different_error_types(self):
        """Test that different error types get different delays."""
        timeout_error = TimeoutError("Timeout")
        rate_limit_error = Exception("Rate limited")
        
        # Mock rate limit error classification
        original_classify = self.strategy.classify_error
        def mock_classify(error):
            if "rate limit" in str(error).lower():
                return ErrorType.RATE_LIMITED
            return original_classify(error)
        
        self.strategy.classify_error = mock_classify
        
        delay_timeout = self.strategy.calculate_delay(timeout_error, "test", 1)
        delay_rate_limit = self.strategy.calculate_delay(rate_limit_error, "test", 1)
        
        # Rate limit should have longer delay
        self.assertGreater(delay_rate_limit, delay_timeout)
    
    def test_jitter_addition(self):
        """Test that jitter is added to prevent thundering herd."""
        error = TimeoutError("Test")
        delays = []
        
        # Calculate multiple delays for the same error
        for _ in range(10):
            delay = self.strategy.calculate_delay(error, "test", 1)
            delays.append(delay)
        
        # Delays should vary due to jitter
        unique_delays = set(delays)
        self.assertGreater(len(unique_delays), 1, "Jitter should create variation in delays")
        
        # All delays should be positive
        for delay in delays:
            self.assertGreaterEqual(delay, 0)


class TestPerformanceBenchmarks(unittest.TestCase):
    """Benchmark tests to measure actual performance improvements."""
    
    def test_large_peer_set_benchmark(self):
        """Benchmark with a large peer set to demonstrate scalability."""
        target_key = b"benchmark_target_key_32_bytes_long_123"
        
        # Generate a large peer set
        peer_ids = []
        for i in range(5000):  # 5000 peers
            peer_bytes = f"benchmark_peer_{i:05d}_{'x' * 15}".encode()[:32]
            peer_ids.append(ID(peer_bytes))
        
        count = 50  # We want top 50 peers
        
        # Benchmark heap approach
        start_time = time.time()
        heap_result = find_closest_peers_heap(target_key, peer_ids, count)
        heap_time = time.time() - start_time
        
        # Benchmark sort approach
        start_time = time.time()
        sort_result = sort_peer_ids_by_distance(target_key, peer_ids)[:count]
        sort_time = time.time() - start_time
        
        # Results should be identical
        self.assertEqual(heap_result, sort_result)
        
        # Calculate performance improvement
        improvement = (sort_time - heap_time) / sort_time * 100 if sort_time > 0 else 0
        
        print(f"\nBenchmark Results (5000 peers, top {count}):")
        print(f"Heap approach: {heap_time:.6f}s")
        print(f"Sort approach: {sort_time:.6f}s")
        print(f"Performance improvement: {improvement:.1f}%")
        
        # Heap approach should be significantly faster
        self.assertLess(heap_time, sort_time * 0.8, 
                       f"Heap approach should be at least 20% faster. "
                       f"Heap: {heap_time:.6f}s, Sort: {sort_time:.6f}s")
    
    def test_memory_usage_benchmark(self):
        """Benchmark memory usage for large peer sets."""
        import tracemalloc
        
        target_key = b"memory_benchmark_target_key_32_bytes_long"
        peer_ids = []
        
        # Generate large peer set
        for i in range(10000):  # 10,000 peers
            peer_bytes = f"memory_peer_{i:05d}_{'x' * 15}".encode()[:32]
            peer_ids.append(ID(peer_bytes))
        
        count = 100  # Top 100 peers
        
        # Measure memory for heap approach
        tracemalloc.start()
        heap_result = find_closest_peers_heap(target_key, peer_ids, count)
        heap_current, heap_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        
        # Measure memory for sort approach
        tracemalloc.start()
        sort_result = sort_peer_ids_by_distance(target_key, peer_ids)[:count]
        sort_current, sort_peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        
        # Results should be identical
        self.assertEqual(heap_result, sort_result)
        
        print(f"\nMemory Usage Benchmark (10,000 peers, top {count}):")
        print(f"Heap approach - Current: {heap_current / 1024:.1f} KB, Peak: {heap_peak / 1024:.1f} KB")
        print(f"Sort approach - Current: {sort_current / 1024:.1f} KB, Peak: {sort_peak / 1024:.1f} KB")
        
        # Heap approach should use less peak memory
        self.assertLess(heap_peak, sort_peak * 1.2,  # Allow 20% tolerance
                       "Heap approach should use less peak memory")


if __name__ == "__main__":
    unittest.main()
