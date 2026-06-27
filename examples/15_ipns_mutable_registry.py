"""Example 15: IPNS Mutable Pointer (Versioned Agent Registry).

This example demonstrates how to use the InterPlanetary Name System (IPNS) to
create a stable, mutable pointer that resolves to immutable CIDs. This is
particularly useful for use cases like a versioned AI agent registry, where
the content updates over time but consumers need a single, unchanging address
to fetch the latest version.
"""

import trio

from py_ipfs_lite.config import Config
from py_ipfs_lite.peer import Peer


async def main():
    print("=== Example 15: IPNS Mutable Pointer (Versioned Agent Registry) ===")

    # We use a memory blockstore for a clean, fast example
    peer = Peer(
        Config(reprovide_interval_seconds=-1, blockstore_type="memory"),
        listen_addrs=["/ip4/127.0.0.1/tcp/0"],
    )
    await peer.start()

    print("\n--- Publishing Version 1 ---")
    v1_cid = await peer.add_node(
        {"version": "1.0.0", "agents": ["summarizer", "classifier"]}, codec="dag-cbor"
    )
    print(f"Created Registry v1 DAG: {v1_cid}")

    print("Publishing to IPNS...")
    # IPNS name is the peer's own ID
    name = str(peer.host.id())
    await peer.publish_name(f"/ipfs/{v1_cid}")
    print(f"IPNS name: {name}  →  {v1_cid}")

    print("\n--- Publishing Version 2 ---")
    v2_cid = await peer.add_node(
        {"version": "2.0.0", "agents": ["summarizer", "classifier", "retriever"]},
        codec="dag-cbor",
    )
    print(f"Created Registry v2 DAG: {v2_cid}")

    print("Publishing update to IPNS (name stays the same, CID changes)...")
    await peer.publish_name(f"/ipfs/{v2_cid}")

    print("\n--- Resolving IPNS Name ---")
    print(f"Resolving {name}...")
    resolved = await peer.resolve_name(name)
    print(f"Resolved to: {resolved}")

    # Extract just the CID part from /ipfs/bafy...
    resolved_cid = resolved.replace("/ipfs/", "")
    assert resolved_cid == v2_cid, f"Mismatch: {resolved_cid} != {v2_cid}"

    print("\nFetching latest registry content...")
    registry = await peer.get_node(resolved_cid)
    print(f"Registry contents: {registry}")

    print("\n✓ Mutable pointer updated. The name is stable; the CID changed.")
    await peer.close()


if __name__ == "__main__":
    trio.run(main)
