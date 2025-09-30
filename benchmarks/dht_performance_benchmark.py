#!/usr/bin/env python3
"""
Performance benchmark for DHT lookup optimizations.

This script measures the performance improvements achieved by the heap-based
optimizations compared to the original O(n²) implementation.
"""

import argparse
import statistics
import time
from typing import List

from libp2p.kad_dht.utils import (
    find_closest_peers_heap,
    sort_peer_ids_by_distance,
)
from libp2p.peer.id import ID


def generate_peer_ids(count: int) -> List[ID]:
    """Generate a list of random peer IDs for benchmarking."""
    peer_ids = []
    for i in range(count):
        # Create deterministic but varied peer IDs
        peer_bytes = f"benchmark_peer_{i:06d}_{'x' * 20}".encode()[:32]
        peer_ids.append(ID(peer_bytes))
    return peer_ids


def benchmark_peer_selection(
    peer_count: int, 
    top_k: int, 
    iterations: int = 5
) -> dict:
    """
    Benchmark peer selection algorithms.
    
    :param peer_count: Number of peers to test with
    :param top_k: Number of closest peers to find
    :param iterations: Number of iterations to average over
    :return: Dictionary with benchmark results
    """
    target_key = b"benchmark_target_key_32_bytes_long_12345"
    peer_ids = generate_peer_ids(peer_count)
    
    # Benchmark heap-based approach
    heap_times = []
    for _ in range(iterations):
        start_time = time.time()
        heap_result = find_closest_peers_heap(target_key, peer_ids, top_k)
        heap_times.append(time.time() - start_time)
    
    # Benchmark original sorting approach
    sort_times = []
    for _ in range(iterations):
        start_time = time.time()
        sort_result = sort_peer_ids_by_distance(target_key, peer_ids)[:top_k]
        sort_times.append(time.time() - start_time)
    
    # Verify results are identical
    assert heap_result == sort_result, "Results should be identical"
    
    # Calculate statistics
    heap_mean = statistics.mean(heap_times)
    heap_std = statistics.stdev(heap_times) if len(heap_times) > 1 else 0
    
    sort_mean = statistics.mean(sort_times)
    sort_std = statistics.stdev(sort_times) if len(sort_times) > 1 else 0
    
    improvement = ((sort_mean - heap_mean) / sort_mean * 100) if sort_mean > 0 else 0
    
    return {
        "peer_count": peer_count,
        "top_k": top_k,
        "iterations": iterations,
        "heap_mean": heap_mean,
        "heap_std": heap_std,
        "sort_mean": sort_mean,
        "sort_std": sort_std,
        "improvement_percent": improvement,
        "speedup_factor": sort_mean / heap_mean if heap_mean > 0 else 1.0
    }


def run_scalability_benchmark():
    """Run benchmark across different peer counts to show scalability."""
    print("DHT Performance Optimization Benchmark")
    print("=" * 50)
    print()
    
    # Test different peer counts
    peer_counts = [100, 500, 1000, 2000, 5000]
    top_k_values = [10, 20, 50]
    
    results = []
    
    for peer_count in peer_counts:
        print(f"Testing with {peer_count:,} peers:")
        
        for top_k in top_k_values:
            result = benchmark_peer_selection(peer_count, top_k, iterations=3)
            results.append(result)
            
            print(f"  Top {top_k:2d}: Heap {result['heap_mean']:.6f}s, "
                  f"Sort {result['sort_mean']:.6f}s, "
                  f"Improvement: {result['improvement_percent']:.1f}% "
                  f"(Speedup: {result['speedup_factor']:.2f}x)")
        
        print()
    
    # Summary
    print("Summary:")
    print("-" * 30)
    
    improvements = [r['improvement_percent'] for r in results]
    speedups = [r['speedup_factor'] for r in results]
    
    print(f"Average improvement: {statistics.mean(improvements):.1f}%")
    print(f"Average speedup: {statistics.mean(speedups):.2f}x")
    print(f"Best improvement: {max(improvements):.1f}%")
    print(f"Best speedup: {max(speedups):.2f}x")
    
    return results


def run_memory_benchmark():
    """Run memory usage benchmark."""
    print("\nMemory Usage Benchmark")
    print("=" * 30)
    
    import tracemalloc
    
    target_key = b"memory_benchmark_target_key_32_bytes_long"
    peer_count = 10000
    top_k = 100
    
    peer_ids = generate_peer_ids(peer_count)
    
    # Measure heap approach memory
    tracemalloc.start()
    heap_result = find_closest_peers_heap(target_key, peer_ids, top_k)
    heap_current, heap_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    
    # Measure sort approach memory
    tracemalloc.start()
    sort_result = sort_peer_ids_by_distance(target_key, peer_ids)[:top_k]
    sort_current, sort_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    
    print(f"Peer count: {peer_count:,}, Top K: {top_k}")
    print(f"Heap approach - Current: {heap_current / 1024:.1f} KB, Peak: {heap_peak / 1024:.1f} KB")
    print(f"Sort approach - Current: {sort_current / 1024:.1f} KB, Peak: {sort_peak / 1024:.1f} KB")
    
    memory_improvement = ((sort_peak - heap_peak) / sort_peak * 100) if sort_peak > 0 else 0
    print(f"Memory improvement: {memory_improvement:.1f}%")


def main():
    """Main benchmark function."""
    parser = argparse.ArgumentParser(description="DHT Performance Benchmark")
    parser.add_argument("--peer-count", type=int, default=1000, 
                       help="Number of peers to test with")
    parser.add_argument("--top-k", type=int, default=20, 
                       help="Number of closest peers to find")
    parser.add_argument("--iterations", type=int, default=5, 
                       help="Number of iterations to average over")
    parser.add_argument("--scalability", action="store_true", 
                       help="Run scalability benchmark across different peer counts")
    parser.add_argument("--memory", action="store_true", 
                       help="Run memory usage benchmark")
    
    args = parser.parse_args()
    
    if args.scalability:
        run_scalability_benchmark()
    elif args.memory:
        run_memory_benchmark()
    else:
        # Single benchmark
        result = benchmark_peer_selection(args.peer_count, args.top_k, args.iterations)
        
        print(f"DHT Performance Benchmark")
        print(f"Peer count: {result['peer_count']:,}")
        print(f"Top K: {result['top_k']}")
        print(f"Iterations: {result['iterations']}")
        print()
        print(f"Heap approach: {result['heap_mean']:.6f}s ± {result['heap_std']:.6f}s")
        print(f"Sort approach: {result['sort_mean']:.6f}s ± {result['sort_std']:.6f}s")
        print(f"Improvement: {result['improvement_percent']:.1f}%")
        print(f"Speedup: {result['speedup_factor']:.2f}x")


if __name__ == "__main__":
    main()
