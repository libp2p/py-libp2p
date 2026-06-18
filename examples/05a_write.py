import trio
from py_ipfs_lite.peer import Peer
from py_ipfs_lite.config import Config


async def main():
    config = Config(
        blockstore_type="filesystem",
        blockstore_path="./demo_blocks",
        reprovide_interval_seconds=-1,
    )
    peer = Peer(config, listen_addrs=["/ip4/127.0.0.1/tcp/0"])
    await peer.start()

    cid = await peer.add_node({"note": "this should survive a process restart"})
    print("Stored node. CID:", cid)
    print("Copy this CID — pass it to demo_5b_read.py")

    await peer.close()


if __name__ == "__main__":
    trio.run(main)
