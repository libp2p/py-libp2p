import sys
import trio
from py_ipfs_lite.peer import Peer
from py_ipfs_lite.config import Config


async def main(cid):
    config = Config(
        blockstore_type="filesystem",
        blockstore_path="./demo_blocks",
        reprovide_interval_seconds=-1,
    )
    peer = Peer(config, listen_addrs=["/ip4/127.0.0.1/tcp/0"])
    await peer.start()

    node = await peer.get_node(cid)
    print("Fetched after a full process restart:", node)

    assert node == {"note": "this should survive a process restart"}

    await peer.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python demo_5b_read.py <cid>")
        sys.exit(1)
    trio.run(main, sys.argv[1])
