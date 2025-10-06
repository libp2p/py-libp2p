#!/usr/bin/env python3
"""
Comprehensive Bitswap example demonstrating ALL protocol features.

This example shows how to use:
- Bitswap v1.0.0, v1.1.0, and v1.2.0 features
- Block storage and retrieval
- Wantlist management with priorities
- Have/DontHave requests (v1.2.0)
- CIDv0 and CIDv1 (v1.1.0+)
- Block presences (v1.2.0)
- Custom block stores
- File sharing

This is a comprehensive tutorial for developers learning Bitswap.
"""

import argparse
import logging
from pathlib import Path
import sys

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import multiaddr
import trio

from libp2p import new_host
from libp2p.bitswap import (
    BitswapClient,
    BlockStore,
    MemoryBlockStore,
    compute_cid_v0,
    compute_cid_v1,
    config,
    get_cid_prefix,
    verify_cid,
)
from libp2p.peer.peerinfo import info_from_p2p_addr

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("bitswap_comprehensive")
logging.getLogger("libp2p.bitswap").setLevel(logging.DEBUG)


# ============================================================================
# DEMONSTRATION 1: Basic Block Storage and Retrieval
# ============================================================================


async def demo_basic_blocks() -> None:
    """Demonstrate basic block storage and retrieval."""
    print("\n" + "=" * 70)
    print("DEMO 1: Basic Block Storage and Retrieval")
    print("=" * 70)

    # Create a simple in-memory block store
    store = MemoryBlockStore()

    # Create some test data
    data1 = b"Hello, Bitswap!"
    data2 = b"This is another block"
    data3 = b"Content-addressed storage is awesome!"

    # Compute CIDs for the data (CIDv0 for v1.0.0 compatibility)
    cid1 = compute_cid_v0(data1)
    cid2 = compute_cid_v0(data2)
    cid3 = compute_cid_v0(data3)

    print("\n1. Created test blocks:")
    print(f"   Block 1 CID: {cid1.hex()[:32]}...")
    print(f"   Block 1 data: {data1!r}")
    print(f"   Block 2 CID: {cid2.hex()[:32]}...")
    print(f"   Block 3 CID: {cid3.hex()[:32]}...")

    # Store blocks
    await store.put_block(cid1, data1)
    await store.put_block(cid2, data2)
    await store.put_block(cid3, data3)
    print(f"\n2. Stored {store.size()} blocks in the store")

    # Retrieve blocks
    retrieved1 = await store.get_block(cid1)
    print(f"\n3. Retrieved block 1: {retrieved1!r}")

    # Check if block exists
    has_block = await store.has_block(cid2)
    print(f"\n4. Block 2 exists: {has_block}")

    # Verify CID matches data
    is_valid = verify_cid(cid1, data1)
    print(f"\n5. CID verification: {is_valid}")

    print("\n✓ Basic block operations demonstrated")


# ============================================================================
# DEMONSTRATION 2: CID Versions (v1.0.0 vs v1.1.0+)
# ============================================================================


async def demo_cid_versions() -> None:
    """Demonstrate CIDv0 and CIDv1."""
    print("\n" + "=" * 70)
    print("DEMO 2: CID Versions (v1.0.0 uses CIDv0, v1.1.0+ supports CIDv1)")
    print("=" * 70)

    data = b"Test data for CID versions"

    # CIDv0 (used in v1.0.0)
    cid_v0 = compute_cid_v0(data)
    print("\n1. CIDv0 (Bitswap v1.0.0):")
    print(f"   CID: {cid_v0.hex()}")
    print(f"   Length: {len(cid_v0)} bytes")

    # CIDv1 (supported in v1.1.0+)
    cid_v1 = compute_cid_v1(data)
    print("\n2. CIDv1 (Bitswap v1.1.0+):")
    print(f"   CID: {cid_v1.hex()}")
    print(f"   Length: {len(cid_v1)} bytes")

    # CID prefix (v1.1.0+ Block messages)
    prefix = get_cid_prefix(cid_v1)
    print("\n3. CID Prefix (for v1.1.0+ payload):")
    print(f"   Prefix: {prefix.hex()}")
    print("   This is sent separately from block data")

    print("\n✓ CID version handling demonstrated")


# ============================================================================
# DEMONSTRATION 3: Wantlist Management with Priorities
# ============================================================================


async def demo_wantlist_management() -> None:
    """Demonstrate wantlist with different priorities."""
    print("\n" + "=" * 70)
    print("DEMO 3: Wantlist Management with Priorities")
    print("=" * 70)

    host = new_host()
    listen_addr = multiaddr.Multiaddr("/ip4/127.0.0.1/tcp/0")

    async with host.run([listen_addr]), trio.open_nursery() as nursery:
        bitswap = BitswapClient(host)
        bitswap.set_nursery(nursery)
        await bitswap.start()

        # Create test CIDs
        cid_high = compute_cid_v0(b"High priority block")
        cid_normal = compute_cid_v0(b"Normal priority block")
        cid_low = compute_cid_v0(b"Low priority block")

        print("\n1. Adding blocks to wantlist with different priorities:")

        # Add with high priority
        await bitswap.want_block(cid_high, priority=10)
        print(f"   ✓ High priority (10): {cid_high.hex()[:32]}...")

        # Add with normal priority
        await bitswap.want_block(cid_normal, priority=5)
        print(f"   ✓ Normal priority (5): {cid_normal.hex()[:32]}...")

        # Add with low priority
        await bitswap.want_block(cid_low, priority=1)
        print(f"   ✓ Low priority (1): {cid_low.hex()[:32]}...")

        print(f"\n2. Wantlist now contains {len(bitswap._wantlist)} entries")

        # Cancel a want
        await bitswap.cancel_want(cid_low)
        print("\n3. Cancelled low priority block")
        print(f"   Wantlist now contains {len(bitswap._wantlist)} entries")

        await bitswap.stop()

    print("\n✓ Wantlist management demonstrated")


# ============================================================================
# DEMONSTRATION 4: Have/DontHave Requests (v1.2.0)
# ============================================================================


async def demo_have_dont_have() -> None:
    """Demonstrate Have/DontHave requests (v1.2.0 feature)."""
    print("\n" + "=" * 70)
    print("DEMO 4: Have/DontHave Requests (Bitswap v1.2.0)")
    print("=" * 70)

    # Create two hosts
    host1 = new_host()
    host2 = new_host()

    addr1 = multiaddr.Multiaddr("/ip4/127.0.0.1/tcp/0")
    addr2 = multiaddr.Multiaddr("/ip4/127.0.0.1/tcp/0")

    async with host1.run([addr1]), host2.run([addr2]), trio.open_nursery() as nursery:
        # Setup bitswap on both hosts (v1.2.0)
        bitswap1 = BitswapClient(host1, protocol_version=config.BITSWAP_PROTOCOL_V120)
        bitswap2 = BitswapClient(host2, protocol_version=config.BITSWAP_PROTOCOL_V120)

        bitswap1.set_nursery(nursery)
        bitswap2.set_nursery(nursery)

        await bitswap1.start()
        await bitswap2.start()

        # Add a block to host1
        test_data = b"Test block for Have/DontHave demo"
        test_cid = compute_cid_v0(test_data)
        await bitswap1.add_block(test_cid, test_data)

        print(f"\n1. Added block to host1: {test_cid.hex()[:32]}...")

        # Connect hosts
        host1_addr = host1.get_addrs()[0]
        host1_info = info_from_p2p_addr(host1_addr)
        await host2.connect(host1_info)

        print("\n2. Connected host2 to host1")

        # Use Have request (v1.2.0) - ask if peer has block without
        # requesting full block
        print("\n3. Sending Have request (not requesting full block)...")
        await bitswap2.want_block(
            test_cid,
            priority=1,
            want_type=1,  # Have request
            send_dont_have=True,  # Request DontHave response if not found
        )

        # Request a non-existent block with DontHave
        missing_cid = compute_cid_v0(b"This block doesn't exist")
        print("\n4. Requesting non-existent block with DontHave enabled...")
        await bitswap2.want_block(
            missing_cid,
            priority=1,
            want_type=1,  # Have request
            send_dont_have=True,
        )

        await trio.sleep(1)  # Allow time for protocol exchange

        await bitswap1.stop()
        await bitswap2.stop()

    print("\n✓ Have/DontHave demonstrated (v1.2.0 feature)")


# ============================================================================
# DEMONSTRATION 5: Protocol Version Negotiation
# ============================================================================


async def demo_protocol_versions() -> None:
    """Demonstrate protocol version negotiation."""
    print("\n" + "=" * 70)
    print("DEMO 5: Protocol Version Negotiation")
    print("=" * 70)

    host1 = new_host()
    host2 = new_host()
    host3 = new_host()

    addr1 = multiaddr.Multiaddr("/ip4/127.0.0.1/tcp/0")
    addr2 = multiaddr.Multiaddr("/ip4/127.0.0.1/tcp/0")
    addr3 = multiaddr.Multiaddr("/ip4/127.0.0.1/tcp/0")

    async with (
        host1.run([addr1]),
        host2.run([addr2]),
        host3.run([addr3]),
        trio.open_nursery() as nursery,
    ):
        # Create clients with different protocol versions
        bitswap_v100 = BitswapClient(
            host1, protocol_version=config.BITSWAP_PROTOCOL_V100
        )
        bitswap_v110 = BitswapClient(
            host2, protocol_version=config.BITSWAP_PROTOCOL_V110
        )
        bitswap_v120 = BitswapClient(
            host3, protocol_version=config.BITSWAP_PROTOCOL_V120
        )

        bitswap_v100.set_nursery(nursery)
        bitswap_v110.set_nursery(nursery)
        bitswap_v120.set_nursery(nursery)

        await bitswap_v100.start()
        await bitswap_v110.start()
        await bitswap_v120.start()

        print("\n1. Started three Bitswap clients:")
        print(f"   - Host 1: {config.BITSWAP_PROTOCOL_V100}")
        print(f"   - Host 2: {config.BITSWAP_PROTOCOL_V110}")
        print(f"   - Host 3: {config.BITSWAP_PROTOCOL_V120}")

        print("\n2. All versions are backwards compatible")
        print("   - v1.2.0 clients can talk to v1.0.0 clients")
        print("   - Protocol is negotiated during connection")

        await bitswap_v100.stop()
        await bitswap_v110.stop()
        await bitswap_v120.stop()

    print("\n✓ Protocol version negotiation demonstrated")


# ============================================================================
# DEMONSTRATION 6: File Sharing
# ============================================================================


async def demo_file_sharing() -> None:
    """Demonstrate file sharing by splitting into blocks."""
    print("\n" + "=" * 70)
    print("DEMO 6: File Sharing (Split file into blocks)")
    print("=" * 70)

    # Create a test file
    test_content = b"This is a test file for Bitswap demonstration.\n" * 50
    print(f"\n1. Created test file: {len(test_content)} bytes")

    # Split into blocks
    block_size = 256  # 256 bytes per block
    blocks = []
    cids = []

    for i in range(0, len(test_content), block_size):
        chunk = test_content[i : i + block_size]
        cid = compute_cid_v0(chunk)
        blocks.append((cid, chunk))
        cids.append(cid)

    print(f"\n2. Split into {len(blocks)} blocks of ~{block_size} bytes each")
    print("   Block CIDs:")
    for i, cid in enumerate(cids[:5]):  # Show first 5
        print(f"   [{i}] {cid.hex()[:40]}...")
    if len(cids) > 5:
        print(f"   ... and {len(cids) - 5} more")

    # Store blocks in a block store
    store = MemoryBlockStore()
    for cid, data in blocks:
        await store.put_block(cid, data)

    print(f"\n3. Stored all {len(blocks)} blocks")

    # Retrieve and reconstruct file
    reconstructed = b""
    for cid in cids:
        block_data = await store.get_block(cid)
        if block_data is not None:
            reconstructed += block_data

    print(f"\n4. Retrieved and reconstructed file: {len(reconstructed)} bytes")
    print(f"   File matches original: {reconstructed == test_content}")

    print("\n✓ File sharing demonstrated")


# ============================================================================
# DEMONSTRATION 7: Custom Block Store
# ============================================================================


class CountingBlockStore(BlockStore):
    """Custom block store that counts operations."""

    def __init__(self) -> None:
        self._store: dict[bytes, bytes] = {}
        self.get_count = 0
        self.put_count = 0
        self.has_count = 0
        self.delete_count = 0

    async def get_block(self, cid: bytes) -> bytes | None:
        self.get_count += 1
        return self._store.get(cid)

    async def put_block(self, cid: bytes, data: bytes) -> None:
        self.put_count += 1
        self._store[cid] = data

    async def has_block(self, cid: bytes) -> bool:
        self.has_count += 1
        return cid in self._store

    async def delete_block(self, cid: bytes) -> None:
        self.delete_count += 1
        if cid in self._store:
            del self._store[cid]


async def demo_custom_block_store() -> None:
    """Demonstrate custom block store implementation."""
    print("\n" + "=" * 70)
    print("DEMO 7: Custom Block Store Implementation")
    print("=" * 70)

    store = CountingBlockStore()

    # Perform some operations
    cid1 = compute_cid_v0(b"Block 1")
    cid2 = compute_cid_v0(b"Block 2")

    await store.put_block(cid1, b"Block 1")
    await store.put_block(cid2, b"Block 2")
    await store.has_block(cid1)
    await store.get_block(cid1)
    await store.delete_block(cid2)

    print("\n1. Custom block store statistics:")
    print(f"   - put_block() called: {store.put_count} times")
    print(f"   - get_block() called: {store.get_count} times")
    print(f"   - has_block() called: {store.has_count} times")
    print(f"   - delete_block() called: {store.delete_count} times")

    print("\n2. You can implement custom stores for:")
    print("   - File system storage")
    print("   - Database storage (SQLite, PostgreSQL)")
    print("   - Distributed storage")
    print("   - Cached storage with LRU eviction")

    print("\n✓ Custom block store demonstrated")


# ============================================================================
# DEMONSTRATION 8: Full Provider-Client Exchange
# ============================================================================


async def demo_provider_client() -> None:
    """Demonstrate complete provider-client block exchange."""
    print("\n" + "=" * 70)
    print("DEMO 8: Complete Provider-Client Block Exchange")
    print("=" * 70)

    # Create provider and client hosts
    provider_host = new_host()
    client_host = new_host()

    provider_addr = multiaddr.Multiaddr("/ip4/127.0.0.1/tcp/0")
    client_addr = multiaddr.Multiaddr("/ip4/127.0.0.1/tcp/0")

    async with (
        provider_host.run([provider_addr]),
        client_host.run([client_addr]),
        trio.open_nursery() as nursery,
    ):
        # Setup provider with v1.2.0
        provider_store = MemoryBlockStore()
        provider = BitswapClient(
            provider_host, provider_store, protocol_version=config.BITSWAP_PROTOCOL_V120
        )
        provider.set_nursery(nursery)
        await provider.start()

        # Add blocks to provider
        blocks_data = [
            b"Hello from Bitswap!",
            b"This is block number 2",
            b"Bitswap makes file sharing easy",
            b"Content-addressed storage rocks!",
        ]
        block_cids = []

        for data in blocks_data:
            cid = compute_cid_v0(data)
            await provider.add_block(cid, data)
            block_cids.append(cid)

        print("\n1. Provider setup complete:")
        print(f"   - Protocol: {config.BITSWAP_PROTOCOL_V120}")
        print(f"   - Blocks available: {provider_store.size()}")

        # Setup client with v1.2.0
        client_store = MemoryBlockStore()
        client = BitswapClient(
            client_host, client_store, protocol_version=config.BITSWAP_PROTOCOL_V120
        )
        client.set_nursery(nursery)
        await client.start()

        print("\n2. Client setup complete:")
        print(f"   - Protocol: {config.BITSWAP_PROTOCOL_V120}")
        print(f"   - Blocks available: {client_store.size()}")

        # Connect client to provider
        provider_host_addr = provider_host.get_addrs()[0]
        provider_info = info_from_p2p_addr(provider_host_addr)
        await client_host.connect(provider_info)

        print("\n3. Client connected to provider")

        # Client requests blocks with different priorities
        print("\n4. Requesting blocks with different priorities:")
        for i, cid in enumerate(block_cids):
            priority = 10 - i  # Decreasing priority
            print(f"   - Block {i}: priority {priority}")
            await client.want_block(cid, priority=priority)

        # Request blocks
        print("\n5. Fetching blocks...")
        for i, cid in enumerate(block_cids):
            try:
                data = await client.get_block(cid, provider_info.peer_id, timeout=5)
                print(f"   ✓ Block {i}: {data.decode()[:50]}...")
            except Exception as e:
                print(f"   ✗ Block {i}: {e}")

        print(f"\n6. Client now has {client_store.size()} blocks")

        await provider.stop()
        await client.stop()

    print("\n✓ Provider-client exchange demonstrated")


# ============================================================================
# MAIN DEMO RUNNER
# ============================================================================


async def run_all_demos() -> None:
    """Run all demonstrations."""
    print("\n" + "=" * 70)
    print("COMPREHENSIVE BITSWAP DEMONSTRATION")
    print("Showing ALL main functions across v1.0.0, v1.1.0, and v1.2.0")
    print("=" * 70)

    demos = [
        ("Basic Block Storage", demo_basic_blocks),
        ("CID Versions", demo_cid_versions),
        ("Wantlist Management", demo_wantlist_management),
        ("Have/DontHave (v1.2.0)", demo_have_dont_have),
        ("Protocol Versions", demo_protocol_versions),
        ("File Sharing", demo_file_sharing),
        ("Custom Block Store", demo_custom_block_store),
        ("Provider-Client", demo_provider_client),
    ]

    for name, demo_func in demos:
        try:
            await demo_func()
            await trio.sleep(0.5)  # Brief pause between demos
        except Exception as e:
            logger.error(f"Demo '{name}' failed: {e}", exc_info=True)

    print("\n" + "=" * 70)
    print("ALL DEMONSTRATIONS COMPLETE!")
    print("=" * 70)
    print("\nYou've seen:")
    print("✓ Block storage and retrieval")
    print("✓ CIDv0 and CIDv1 (v1.0.0 vs v1.1.0+)")
    print("✓ Wantlist management with priorities")
    print("✓ Have/DontHave requests (v1.2.0)")
    print("✓ Protocol version negotiation")
    print("✓ File sharing by splitting into blocks")
    print("✓ Custom block store implementation")
    print("✓ Complete provider-client exchange")
    print("\nCheck the code to learn how each feature works!")


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Comprehensive Bitswap demonstration",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
This example demonstrates ALL main Bitswap functions:

1. Basic block storage and retrieval
2. CID versions (v0 and v1)
3. Wantlist management with priorities
4. Have/DontHave requests (v1.2.0)
5. Protocol version negotiation
6. File sharing
7. Custom block stores
8. Provider-client exchange

Run without arguments to see all demonstrations.
        """,
    )

    parser.add_argument(
        "--demo",
        choices=[
            "all",
            "basic",
            "cid",
            "wantlist",
            "have",
            "versions",
            "file",
            "custom",
            "exchange",
        ],
        default="all",
        help="Which demonstration to run",
    )

    args = parser.parse_args()

    try:
        if args.demo == "all":
            trio.run(run_all_demos)
        elif args.demo == "basic":
            trio.run(demo_basic_blocks)
        elif args.demo == "cid":
            trio.run(demo_cid_versions)
        elif args.demo == "wantlist":
            trio.run(demo_wantlist_management)
        elif args.demo == "have":
            trio.run(demo_have_dont_have)
        elif args.demo == "versions":
            trio.run(demo_protocol_versions)
        elif args.demo == "file":
            trio.run(demo_file_sharing)
        elif args.demo == "custom":
            trio.run(demo_custom_block_store)
        elif args.demo == "exchange":
            trio.run(demo_provider_client)
    except KeyboardInterrupt:
        logger.info("\nExiting...")
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
