import logging

import trio

from py_ipfs_lite.config import Config
from py_ipfs_lite.peer import Peer

logging.getLogger("py_ipfs_lite.reprovider").setLevel(logging.WARNING)


async def main():
    print("Demo 5a: Writing data to disk (persistence test)")

    print("\nStarting an IPFS Peer (Writer)...")
    config = Config(
        blockstore_type="filesystem",
        blockstore_path="./demo_blocks",
        reprovide_interval_seconds=-1,
    )
    peer = Peer(config, listen_addrs=["/ip4/127.0.0.1/tcp/0"])
    await peer.start()

    print(f"Peer initialized with Peer ID: {peer.host.id()}")
    print(f"Listening on multiaddr: {peer.host.addrs()[0]}")

    print("\nCreating and storing an IPLD node...")
    cid = await peer.add_node({"note": "this should survive a process restart"})
    print(f"Stored node successfully.\nCID: {cid}")

    print("\nInstruction:")
    print("Copy this CID and pass it to '05b_localstore_read.py'")
    print(f"Example: python examples/05b_localstore_read.py {cid}")

    print("\nClosing the peer cleanly...")
    await peer.close()


if __name__ == "__main__":
    trio.run(main)
