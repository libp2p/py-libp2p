import sys
import trio
import logging
from py_ipfs_lite.peer import Peer
from py_ipfs_lite.config import Config

logging.getLogger("py_ipfs_lite.reprovider").setLevel(logging.WARNING)

async def main(cid: str):
    print("Demo 5b: Reading data from disk (persistence test)")
    
    print("\nStarting an IPFS Peer (Reader)...")
    config = Config(
        blockstore_type="filesystem",
        blockstore_path="./demo_blocks",
        reprovide_interval_seconds=-1,
    )
    peer = Peer(config, listen_addrs=["/ip4/127.0.0.1/tcp/0"])
    await peer.start()
    
    print(f"Peer initialized with Peer ID: {peer.host.id()}")
    print(f"Listening on multiaddr: {peer.host.addrs()[0]}")

    print(f"\nAttempting to read node from local blockstore...\nTarget CID: {cid}")
    try:
        data = await peer.get_node(cid)
        print("\nSuccessfully read node from disk:")
        print(data)
    except Exception as e:
        print(f"\nFailed to read node: {e}")
    finally:
        print("\nClosing the peer cleanly...")
        await peer.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python examples/05b_localstore_read.py <cid>")
        sys.exit(1)
    trio.run(main, sys.argv[1])
