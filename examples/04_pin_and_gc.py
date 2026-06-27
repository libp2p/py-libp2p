"""Example 04: Pinning and Garbage Collection (GC).

This demo illustrates fundamental IPFS blockstore management. It demonstrates
how to safely pin essential blocks to protect them from deletion, and how to
run a garbage collection sweep to reclaim storage from unpinned, orphaned blocks.
"""

import logging

import trio
from libp2p.bitswap.cid import parse_cid

from py_ipfs_lite.config import Config
from py_ipfs_lite.peer import Peer

logging.getLogger("py_ipfs_lite.reprovider").setLevel(logging.WARNING)


async def main():
    print("Demo 4: Pinning + garbage collection")

    print("\nStarting an IPFS Peer...")
    peer = Peer(
        Config(reprovide_interval_seconds=-1), listen_addrs=["/ip4/127.0.0.1/tcp/0"]
    )
    await peer.start()
    print(f"Peer initialized with Peer ID: {peer.host.id()}")
    print(f"Listening on multiaddr: {peer.host.addrs()[0]}")

    print("\nStoring two nodes in the blockstore...")
    cid_keep = await peer.add_node({"name": "pinned-log"})
    cid_drop = await peer.add_node({"name": "unpinned-log"})
    print(f"Node to keep:\nCID: {cid_keep}\n")
    print(f"Node to drop:\nCID: {cid_drop}")

    print("\nPinning the first node to prevent garbage collection...")
    await peer.add_pin(cid_keep, recursive=False)
    print(f"Successfully pinned:\nCID: {cid_keep}")

    print("\nTriggering Garbage Collection (GC)...")
    stats = await peer.gc()
    print("GC statistics returned by daemon:")
    print(f"  Blocks reclaimed: {stats.reclaimed_blocks}")
    print(f"  Blocks retained:  {stats.retained_blocks}")

    print("\nVerifying block presence on disk...")
    keep_present = await peer.blockstore.has(parse_cid(cid_keep))
    drop_present = await peer.blockstore.has(parse_cid(cid_drop))

    print(f"Pinned block still present:   {keep_present}")
    print(f"Unpinned block still present: {drop_present}")

    assert keep_present is True
    assert drop_present is False
    print(
        "\nAssertions passed! Garbage collection successfully removed only the unpinned block."
    )

    print("\nClosing the peer cleanly...")
    await peer.close()


if __name__ == "__main__":
    trio.run(main)
