#!/usr/bin/env python

"""
Grid Topology DHT Example

This example demonstrates how to use the Grid Topology routing table
with py-libp2p's Kademlia DHT. Grid topology provides a fixed 256-bucket
structure based on Common Prefix Length (CPL) indexing, matching cpp-libp2p.

Grid Topology is useful when:
- You need better interoperability with cpp-libp2p or Go-libp2p
- You prefer a simpler, more predictable bucket structure
- You need explicit peer state management (temporary vs permanent peers)
"""

import logging

from libp2p.kad_dht.grid_routing_table import GridRoutingTable, NodeId
from libp2p.kad_dht.grid_topology_config import (
    get_default_config,
)
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import PeerInfo

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def example_basic_grid_topology():
    """Basic usage of Grid Topology routing table."""
    print("\nBasic Grid Topology Usage\n")

    # Create local node ID
    local_id = ID.from_base58("QmaCpDMGvV2BGHeYERUEnRQAwe5CcqarqmtA7xNXT92p2")
    print(f"Local Node ID: {local_id}")

    # Create grid routing table with default config
    config = get_default_config()
    rt = GridRoutingTable(local_id, max_bucket_size=config.max_bucket_size)
    print("Created Grid Topology with 256 fixed buckets\n")

    # Create some test peers
    peer_ids = [
        ID.from_base58("QmZLaXk3bbiHgVK3zp5A8n2DEuvMZFRv1GAjTrSvZuLnFr"),
        ID.from_base58("QmdgB6x6xfBLvV9VwSPj9D7aHCmXhvEVVBn2CUEbNJnTg"),
        ID.from_base58("QmYPp4CUQpRcpHBqWgmQ4TjqW9AHJ3qLhQV5d7s3d8hMJx"),
    ]

    # Add peers to the routing table
    print("Adding peers to routing table:")
    for peer_id in peer_ids:
        peer_info = PeerInfo(peer_id, [])
        success = rt.update(peer_id, peer_info=peer_info, is_permanent=True)

        if success:
            node_id = NodeId(peer_id)
            bucket_index = rt._get_bucket_index(node_id)
            print(f"  ✓ Added peer to bucket {bucket_index}")
        else:
            print("  ✗ Failed to add peer")

    print(f"\nTotal peers in routing table: {rt.size()}\n")
    return rt, local_id, peer_ids


def example_peer_lookup(rt, peer_ids):
    """Demonstrate peer lookup in grid topology."""
    print("Peer Lookup\n")

    for peer_id in peer_ids:
        if rt.contains(peer_id):
            print(f"✓ Peer {str(peer_id)[:16]}... found in routing table")

            # Get peer info from the bucket
            node_id = NodeId(peer_id)
            bucket_index = rt._get_bucket_index(node_id)
            if bucket_index is not None:
                bucket = rt.get_bucket(bucket_index)
                if bucket:
                    peer_info = bucket.get_peer_info(peer_id)
                    if peer_info:
                        print(f"  Peer info: {peer_info}\n")
        else:
            print(f"✗ Peer {str(peer_id)[:16]}... NOT found\n")


def example_bucket_distribution(rt):
    """Show how peers are distributed across buckets."""
    print("Bucket Distribution\n")

    stats = rt.get_bucket_stats()
    print(f"Total peers: {stats['total_peers']}")
    print(f"Total buckets: {stats['total_buckets']}")
    print(f"Non-empty buckets: {stats['non_empty_buckets']}")

    if stats["total_peers"] > 0:
        avg = stats["total_peers"] / max(1, stats["non_empty_buckets"])
        print(f"Average peers per bucket: {avg:.1f}\n")


def example_grid_topology_advantages():
    """Explain advantages of grid topology."""
    print("Grid Topology Advantages\n")

    print("1. Fixed 256 Buckets")
    print("   - One bucket per bit in 256-bit ID space")
    print("   - No dynamic splitting complexity")
    print("   - Predictable bucket structure\n")

    print("2. CPL-Based Indexing")
    print("   - Bucket index = 255 - CPL(local_id, peer_id)")
    print("   - CPL = Common Prefix Length")
    print("   - Simpler than XOR range-based indexing\n")

    print("3. Explicit Peer States")
    print("   - Permanent peers: Critical connections")
    print("   - Temporary peers: Can be replaced")
    print("   - Better control over peer replacement\n")

    print("4. Cross-Implementation Compatibility")
    print("   - Matches cpp-libp2p specification")
    print("   - Compatible with Go-libp2p grid topology")
    print("   - Better interoperability\n")


def example_compare_with_standard_kbucket():
    """Show how grid topology differs from standard k-bucket."""
    print("Grid Topology vs Standard K-Bucket\n")

    print("Standard K-Bucket:")
    print("  - Dynamic buckets (starts with 1, splits as needed)")
    print("  - XOR range-based indexing")
    print("  - Implicit LRU peer ordering")
    print("  - Good for general use cases\n")

    print("Grid Topology:")
    print("  - Fixed 256 buckets")
    print("  - CPL-based indexing")
    print("  - Explicit MRU peer ordering")
    print("  - Better for cross-implementation scenarios\n")

    print("Choice:")
    print("  from libp2p.kad_dht import RoutingTable")
    print("  rt = RoutingTable(local_id)  # Standard k-bucket\n")

    print("  from libp2p.kad_dht import GridRoutingTable")
    print("  rt = GridRoutingTable(local_id)  # Grid topology\n")


def main():
    """Run all examples."""
    print("\n" + "=" * 60)
    print("Grid Topology DHT - Comprehensive Example")
    print("=" * 60)

    # Run examples
    rt, local_id, peer_ids = example_basic_grid_topology()
    example_peer_lookup(rt, peer_ids)
    example_bucket_distribution(rt)
    example_grid_topology_advantages()
    example_compare_with_standard_kbucket()

    print("=" * 60)
    print("Examples completed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
