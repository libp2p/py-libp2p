#!/usr/bin/env python3
"""
Example usage of persistent peerstore with safe serialization.

This example demonstrates how to use the new persistent peerstore implementation
with Protocol Buffer serialization instead of unsafe pickle.
"""

import asyncio
from pathlib import Path
import tempfile

from multiaddr import Multiaddr

from libp2p.peer.id import ID
from libp2p.peer.persistent import (
    create_async_peerstore,
    create_sync_peerstore,
)


async def async_example():
    """Demonstrate async persistent peerstore usage."""
    print("=== Async Persistent Peerstore Example ===")

    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "async_peers.db"

        # Create peerstore with safe serialization and configurable sync
        async with create_async_peerstore(
            db_path=db_path,
            backend="sqlite",
            sync_interval=0.5,  # Sync every 0.5 seconds
            auto_sync=True,
        ) as peerstore:
            # Create a test peer
            peer_id = ID.from_string("QmNnooDu7bfjPFoTZYxMNLWUQJyrVwtbZg5gBMjTezGAJN")

            # Add some addresses
            addr1 = Multiaddr("/ip4/127.0.0.1/tcp/4001")
            addr2 = Multiaddr("/ip6/::1/tcp/4001")

            await peerstore.add_addrs_async(peer_id, [addr1, addr2], 3600)

            # Add protocols
            await peerstore.add_protocols_async(
                peer_id, ["/ipfs/ping/1.0.0", "/ipfs/id/1.0.0"]
            )

            # Add metadata
            await peerstore.put_async(peer_id, "agent", "py-libp2p-example")

            print(f"Added peer {peer_id}")
            print(f"Addresses: {await peerstore.addrs_async(peer_id)}")
            print(f"Protocols: {await peerstore.get_protocols_async(peer_id)}")
            print(f"Metadata: {await peerstore.get_async(peer_id, 'agent')}")

        print("Peerstore closed safely using context manager")


def sync_example():
    """Demonstrate sync persistent peerstore usage."""
    print("\n=== Sync Persistent Peerstore Example ===")

    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "sync_peers.db"

        # Create peerstore with safe serialization and configurable sync
        with create_sync_peerstore(
            db_path=db_path,
            backend="sqlite",
            sync_interval=1.0,  # Sync every 1 second
            auto_sync=False,  # Manual sync control
        ) as peerstore:
            # Create a test peer
            peer_id = ID.from_string("QmNnooDu7bfjPFoTZYxMNLWUQJyrVwtbZg5gBMjTezGAJN")

            # Add some addresses
            addr1 = Multiaddr("/ip4/192.168.1.100/tcp/4001")
            addr2 = Multiaddr("/ip4/10.0.0.1/tcp/4001")

            peerstore.add_addrs(peer_id, [addr1, addr2], 7200)

            # Add protocols
            peerstore.add_protocols(peer_id, ["/libp2p/circuit/relay/0.1.0"])

            # Add metadata
            peerstore.put(peer_id, "version", "1.0.0")

            # Manual sync since auto_sync=False
            peerstore.datastore.sync(b"")

            print(f"Added peer {peer_id}")
            print(f"Addresses: {peerstore.addrs(peer_id)}")
            print(f"Protocols: {peerstore.get_protocols(peer_id)}")
            print(f"Metadata: {peerstore.get(peer_id, 'version')}")

        print("Peerstore closed safely using context manager")


def security_example():
    """Demonstrate security improvements."""
    print("\n=== Security Improvements ===")
    print("✅ Replaced unsafe pickle with Protocol Buffers")
    print("✅ Added context manager support for proper resource cleanup")
    print("✅ Improved SQLite thread safety with WAL mode")
    print("✅ Added configurable sync for better performance")
    print("✅ Enhanced error handling with specific exceptions")
    print("✅ Added proper file permissions (0600) for database files")


if __name__ == "__main__":
    # Run async example
    asyncio.run(async_example())

    # Run sync example
    sync_example()

    # Show security improvements
    security_example()

    print("\n🎉 All examples completed successfully!")
    print("The persistent peerstore now uses safe Protocol Buffer serialization")
    print("and provides better resource management and performance control.")
