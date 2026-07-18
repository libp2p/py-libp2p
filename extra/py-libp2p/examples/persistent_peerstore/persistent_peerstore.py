#!/usr/bin/env python3
"""
Example demonstrating the usage of PersistentPeerStore.

This example shows how to use the PersistentPeerStore with different datastore backends
to maintain peer information across application restarts.
"""

from pathlib import Path
import tempfile

from multiaddr import Multiaddr
import trio

from libp2p.peer.id import ID
from libp2p.peer.persistent import (
    AsyncPersistentPeerStore,
    create_async_leveldb_peerstore,
    create_async_memory_peerstore,
    create_async_rocksdb_peerstore,
    create_async_sqlite_peerstore,
)


async def demonstrate_peerstore_operations(
    peerstore: AsyncPersistentPeerStore, name: str
):
    """Demonstrate basic peerstore operations."""
    print(f"\n=== {name} PeerStore Demo ===")

    # Create some test peer IDs
    peer_id_1 = ID.from_string("QmPeer1")
    peer_id_2 = ID.from_string("QmPeer2")

    # Add addresses for peers
    addr1 = Multiaddr("/ip4/127.0.0.1/tcp/4001")
    addr2 = Multiaddr("/ip4/192.168.1.1/tcp/4002")

    print(f"Adding addresses for {peer_id_1}")
    await peerstore.add_addrs_async(peer_id_1, [addr1], 3600)  # 1 hour TTL

    print(f"Adding addresses for {peer_id_2}")
    await peerstore.add_addrs_async(peer_id_2, [addr2], 7200)  # 2 hours TTL

    # Add protocols
    print(f"Adding protocols for {peer_id_1}")
    await peerstore.add_protocols_async(
        peer_id_1, ["/ipfs/ping/1.0.0", "/ipfs/id/1.0.0"]
    )

    print(f"Adding protocols for {peer_id_2}")
    await peerstore.add_protocols_async(
        peer_id_2, ["/ipfs/ping/1.0.0", "/ipfs/kad/1.0.0"]
    )

    # Add metadata
    print(f"Adding metadata for {peer_id_1}")
    await peerstore.put_async(peer_id_1, "agent", "go-libp2p/0.1.0")
    await peerstore.put_async(peer_id_1, "version", "1.0.0")

    print(f"Adding metadata for {peer_id_2}")
    await peerstore.put_async(peer_id_2, "agent", "js-libp2p/0.1.0")
    await peerstore.put_async(peer_id_2, "version", "2.0.0")

    # Record latency metrics
    print(f"Recording latency for {peer_id_1}")
    await peerstore.record_latency_async(peer_id_1, 0.05)  # 50ms

    print(f"Recording latency for {peer_id_2}")
    await peerstore.record_latency_async(peer_id_2, 0.1)  # 100ms

    # Retrieve and display information
    print(f"\nRetrieved peer info for {peer_id_1}:")
    try:
        peer_info = await peerstore.peer_info_async(peer_id_1)
        print(f"  Addresses: {[str(addr) for addr in peer_info.addrs]}")
    except Exception as e:
        print(f"  Error: {e}")

    print(f"\nRetrieved protocols for {peer_id_1}:")
    try:
        protocols = await peerstore.get_protocols_async(peer_id_1)
        print(f"  Protocols: {protocols}")
    except Exception as e:
        print(f"  Error: {e}")

    print(f"\nRetrieved metadata for {peer_id_1}:")
    try:
        agent = await peerstore.get_async(peer_id_1, "agent")
        version = await peerstore.get_async(peer_id_1, "version")
        print(f"  Agent: {agent}")
        print(f"  Version: {version}")
    except Exception as e:
        print(f"  Error: {e}")

    print(f"\nRetrieved latency for {peer_id_1}:")
    try:
        latency = await peerstore.latency_EWMA_async(peer_id_1)
        print(f"  Latency EWMA: {latency:.3f}s")
    except Exception as e:
        print(f"  Error: {e}")

    # List all peers
    peer_ids = await peerstore.peer_ids_async()
    valid_peer_ids = await peerstore.valid_peer_ids_async()
    peers_with_addrs = await peerstore.peers_with_addrs_async()
    print(f"\nAll peer IDs: {[str(pid) for pid in peer_ids]}")
    print(f"Valid peer IDs: {[str(pid) for pid in valid_peer_ids]}")
    print(f"Peers with addresses: {[str(pid) for pid in peers_with_addrs]}")


async def demonstrate_persistence():
    """Demonstrate persistence across restarts."""
    print("\n=== Persistence Demo ===")

    # Create a temporary directory for SQLite database
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "peerstore.db"

        # First session - add some data
        print("First session: Adding peer data...")
        peerstore1 = create_async_sqlite_peerstore(str(db_path))

        peer_id = ID.from_string("QmPersistentPeer")
        addr = Multiaddr("/ip4/10.0.0.1/tcp/4001")

        await peerstore1.add_addrs_async(peer_id, [addr], 3600)
        await peerstore1.add_protocols_async(peer_id, ["/ipfs/ping/1.0.0"])
        await peerstore1.put_async(peer_id, "session", "first")

        print(f"Added peer {peer_id} with address {addr}")
        protocols = await peerstore1.get_protocols_async(peer_id)
        metadata = await peerstore1.get_async(peer_id, "session")
        print(f"Peer protocols: {protocols}")
        print(f"Peer metadata: {metadata}")

        # Close the first peerstore
        await peerstore1.close_async()

        # Second session - data should persist
        print("\nSecond session: Reopening peerstore...")
        peerstore2 = create_async_sqlite_peerstore(str(db_path))

        # Check if data persisted
        try:
            peer_info = await peerstore2.peer_info_async(peer_id)
            protocols = await peerstore2.get_protocols_async(peer_id)
            metadata = await peerstore2.get_async(peer_id, "session")
            print(f"Retrieved peer info: {[str(addr) for addr in peer_info.addrs]}")
            print(f"Retrieved protocols: {protocols}")
            print(f"Retrieved metadata: {metadata}")
            print("✅ Data persisted successfully!")
        except Exception as e:
            print(f"❌ Data did not persist: {e}")

        # Update data in second session
        await peerstore2.put_async(peer_id, "session", "second")
        updated_metadata = await peerstore2.get_async(peer_id, "session")
        print(f"Updated metadata: {updated_metadata}")

        await peerstore2.close_async()


async def demonstrate_different_backends():
    """Demonstrate different datastore backends."""
    print("\n=== Different Backend Demo ===")

    # Memory backend (not persistent)
    print("\n1. Memory Backend (not persistent):")
    memory_peerstore = create_async_memory_peerstore()
    await demonstrate_peerstore_operations(memory_peerstore, "Memory")
    await memory_peerstore.close_async()

    # SQLite backend
    print("\n2. SQLite Backend:")
    with tempfile.TemporaryDirectory() as temp_dir:
        sqlite_peerstore = create_async_sqlite_peerstore(Path(temp_dir) / "sqlite.db")
        await demonstrate_peerstore_operations(sqlite_peerstore, "SQLite")
        await sqlite_peerstore.close_async()

    # LevelDB backend (if available)
    print("\n3. LevelDB Backend:")
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            leveldb_peerstore = create_async_leveldb_peerstore(
                Path(temp_dir) / "leveldb"
            )
            await demonstrate_peerstore_operations(leveldb_peerstore, "LevelDB")
            await leveldb_peerstore.close_async()
    except ImportError:
        print("LevelDB backend not available (plyvel not installed)")

    # RocksDB backend (if available)
    print("\n4. RocksDB Backend:")
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            rocksdb_peerstore = create_async_rocksdb_peerstore(
                Path(temp_dir) / "rocksdb"
            )
            await demonstrate_peerstore_operations(rocksdb_peerstore, "RocksDB")
            await rocksdb_peerstore.close_async()
    except ImportError:
        print("RocksDB backend not available (pyrocksdb not installed)")


async def demonstrate_async_operations():
    """Demonstrate async operations and cleanup."""
    print("\n=== Async Operations Demo ===")

    with tempfile.TemporaryDirectory() as temp_dir:
        peerstore = create_async_sqlite_peerstore(Path(temp_dir) / "async.db")

        # Start cleanup task
        print("Starting cleanup task...")
        async with trio.open_nursery() as nursery:
            nursery.start_soon(peerstore.start_cleanup_task, 1)  # 1 second interval

            # Add some peers
            peer_id = ID.from_string("QmAsyncPeer")
            addr = Multiaddr("/ip4/127.0.0.1/tcp/4001")
            await peerstore.add_addrs_async(peer_id, [addr], 1)  # 1 second TTL

            print("Added peer with 1-second TTL")
            addrs = await peerstore.addrs_async(peer_id)
            print(f"Peer addresses: {[str(addr) for addr in addrs]}")

            # Wait for expiration
            print("Waiting for peer to expire...")
            await trio.sleep(2)

            # Check if peer expired
            try:
                addrs = await peerstore.addrs_async(peer_id)
                print(f"Peer still has addresses: {[str(addr) for addr in addrs]}")
            except Exception as e:
                print(f"Peer expired: {e}")

            # Stop the cleanup task
            nursery.cancel_scope.cancel()

        await peerstore.close_async()


async def main():
    """Main demonstration function."""
    print("PersistentPeerStore Usage Examples")
    print("=" * 50)

    # Demonstrate basic operations
    basic_peerstore = create_async_memory_peerstore()
    await demonstrate_peerstore_operations(basic_peerstore, "Basic")
    await basic_peerstore.close_async()

    # Demonstrate persistence
    await demonstrate_persistence()

    # Demonstrate different backends
    await demonstrate_different_backends()

    # Demonstrate async operations
    await demonstrate_async_operations()

    print("\n" + "=" * 50)
    print("All examples completed!")


if __name__ == "__main__":
    trio.run(main)
