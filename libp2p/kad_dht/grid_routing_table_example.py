"""
Example: Using Grid Topology Routing Table

This example demonstrates how to use the GridRoutingTable implementation
matching the cpp-libp2p grid topology.
"""

from libp2p.kad_dht.grid_routing_table import GridRoutingTable, NodeId
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import PeerInfo


def example_basic_usage():
    """Basic usage of GridRoutingTable."""
    local_id = ID.from_base58("QmaCpDMGvV2BGHeYERUEnRQAwe5CcqarqmtA7xNXT92p2")
    print(f"Local Peer ID: {local_id}")

    rt = GridRoutingTable(local_id, max_bucket_size=20)
    print(f"Created routing table with {rt.max_bucket_size} peers per bucket")
    print("Total buckets: 256\n")

    return local_id, rt


def example_add_peers(rt, local_id):
    """Add peers to the routing table."""
    test_peers = [
        ID.from_base58("QmZLaXk3bbiHgVK3zp5A8n2DEuvMZFRv1GAjTrSvZuLnFr"),
        ID.from_base58("QmdgB6x6xfBLvV9VwSPj9D7aHCmXhvEVVBn2CUEbNJnTg"),
        ID.from_base58("QmYPp4CUQpRcpHBqWgmQ4TjqW9AHJ3qLhQV5d7s3d8hMJx"),
    ]

    for peer_id in test_peers:
        peer_info = PeerInfo(peer_id, [])

        success = rt.update(
            peer_id, peer_info=peer_info, is_permanent=True, is_connected=False
        )

        if success:
            node_id = NodeId(peer_id)
            bucket_index = rt._get_bucket_index(node_id)
            print(f"✓ Added {str(peer_id)[:16]}... to bucket {bucket_index}")
        else:
            print(f"✗ Failed to add {str(peer_id)[:16]}...")

    print(f"\nTotal peers in routing table: {rt.size()}\n")
    return test_peers


def example_peer_lookup(rt, test_peers):
    """Demonstrate peer lookup and retrieval."""
    for peer_id in test_peers:
        if rt.contains(peer_id):
            print(f"✓ {str(peer_id)[:16]}... is in routing table")
        else:
            print(f"✗ {str(peer_id)[:16]}... is NOT in routing table")

    if test_peers:
        peer_info = rt.get_peer_info(test_peers[0])
        if peer_info:
            print(f"\nPeer info for {str(test_peers[0])[:16]}...: {peer_info}")

    print()


def example_nearest_peers(rt, local_id):
    """Find nearest peers to a target key."""
    import hashlib

    target_data = b"example_content"
    target_key = hashlib.sha256(target_data).digest()
    print(f"Target key: {target_key.hex()[:32]}...")

    nearest = rt.get_nearest_peers(target_key, count=5)
    print("\nNearest 5 peers to target:")
    for i, peer_id in enumerate(nearest, 1):
        node_id = NodeId(peer_id)
        bucket_index = rt._get_bucket_index(node_id)
        print(f"  {i}. {str(peer_id)[:16]}... (bucket {bucket_index})")

    print()


def example_bucket_statistics(rt):
    """Display routing table statistics."""
    stats = rt.get_bucket_stats()

    print(f"Total peers: {stats['total_peers']}")
    print(f"Total buckets: {stats['total_buckets']}")
    print(f"Non-empty buckets: {stats['non_empty_buckets']}")
    print(
        f"Average peers per non-empty bucket: "
        f"{stats['total_peers'] / max(1, stats['non_empty_buckets']):.1f}"
    )

    non_empty = [size for size in stats["bucket_distribution"] if size > 0]
    if non_empty:
        print(f"Min peers in bucket: {min(non_empty)}")
        print(f"Max peers in bucket: {max(non_empty)}")

    print()


def example_peer_replacement(rt, local_id):
    """Demonstrate peer replacement logic."""
    small_rt = GridRoutingTable(local_id, max_bucket_size=2)

    peers = [
        ID.from_base58("QmZLaXk3bbiHgVK3zp5A8n2DEuvMZFRv1GAjTrSvZuLnFr"),
        ID.from_base58("QmdgB6x6xfBLvV9VwSPj9D7aHCmXhvEVVBn2CUEbNJnTg"),
    ]

    print("Adding 2 permanent peers to bucket (max_size=2):")
    for peer_id in peers:
        small_rt.update(peer_id, is_permanent=True)
        print(f"  ✓ Added {str(peer_id)[:16]}...")

    temp_peer = ID.from_base58("QmYPp4CUQpRcpHBqWgmQ4TjqW9AHJ3qLhQV5d7s3d8hMJx")

    print(f"\nTrying to add temporary peer {str(temp_peer)[:16]}...")
    success = small_rt.update(temp_peer, is_permanent=False)

    if success:
        print("  ✓ Temporary peer was added (replaced a replaceable peer)")
    else:
        print("  ✗ Temporary peer was rejected (no replaceable peers)")

    print()


def example_xor_distance():
    """Demonstrate XOR distance calculation."""
    peer_id1 = ID.from_base58("QmaCpDMGvV2BGHeYERUEnRQAwe5CcqarqmtA7xNXT92p2")
    peer_id2 = ID.from_base58("QmZLaXk3bbiHgVK3zp5A8n2DEuvMZFRv1GAjTrSvZuLnFr")

    node_id1 = NodeId(peer_id1)
    node_id2 = NodeId(peer_id2)

    distance = node_id1.distance(node_id2)
    print(f"Node 1: {node_id1.data.hex()[:32]}...")
    print(f"Node 2: {node_id2.data.hex()[:32]}...")
    print(f"XOR Distance: {distance.hex()[:32]}...\n")

    cpl = node_id1.common_prefix_len(node_id2)
    print(f"Common Prefix Length: {cpl} bits")
    print(f"Bucket Index: {255 - cpl}")

    print()


def example_remove_peer(rt, test_peers):
    """Remove a peer from the routing table."""
    if test_peers:
        peer_to_remove = test_peers[0]
        print(f"Removing {str(peer_to_remove)[:16]}...")

        success = rt.remove(peer_to_remove)

        if success:
            print("✓ Peer removed successfully")
            if rt.contains(peer_to_remove):
                print("✗ Error: Peer still in table!")
            else:
                print("✓ Verified: Peer no longer in table")
        else:
            print("✗ Failed to remove peer")

        print(f"Total peers remaining: {rt.size()}\n")


def main():
    """Run all examples."""
    print("=" * 60)
    print("Grid Topology (Kademlia DHT) Routing Table Examples")
    print("=" * 60)
    print()

    local_id, rt = example_basic_usage()

    test_peers = example_add_peers(rt, local_id)

    example_peer_lookup(rt, test_peers)

    example_bucket_statistics(rt)

    example_nearest_peers(rt, local_id)

    example_xor_distance()

    example_peer_replacement(rt, local_id)

    example_remove_peer(rt, test_peers)

    print("=" * 60)
    print("Examples completed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
