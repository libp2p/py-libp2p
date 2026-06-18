import trio
from py_ipfs_lite.peer import Peer
from py_ipfs_lite.config import Config
from libp2p.bitswap.cid import parse_cid


async def main():
    peer = Peer(Config(reprovide_interval_seconds=-1), listen_addrs=["/ip4/127.0.0.1/tcp/0"])
    await peer.start()

    cid_keep = await peer.add_node({"name": "pinned-log"})
    cid_drop = await peer.add_node({"name": "unpinned-log"})
    print("Stored two nodes:")
    print("  keep:", cid_keep)
    print("  drop:", cid_drop)

    await peer.add_pin(cid_keep, recursive=False)
    print("Pinned:", cid_keep)

    stats = await peer.gc()
    print("GC stats:", stats)

    keep_present = await peer.blockstore.has(parse_cid(cid_keep))
    drop_present = await peer.blockstore.has(parse_cid(cid_drop))
    print("Pinned block still present:  ", keep_present)
    print("Unpinned block still present:", drop_present)

    assert keep_present is True
    assert drop_present is False

    await peer.close()


if __name__ == "__main__":
    trio.run(main)
