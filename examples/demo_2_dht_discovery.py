import trio
from py_ipfs_lite.peer import Peer
from py_ipfs_lite.config import Config


async def main():
    peer_a = Peer(Config(reprovide_interval_seconds=-1), listen_addrs=["/ip4/127.0.0.1/tcp/0"])
    peer_b = Peer(Config(reprovide_interval_seconds=-1), listen_addrs=["/ip4/127.0.0.1/tcp/0"])

    await peer_a.start()
    await peer_b.start()

    peer_a_addr = str(peer_a.host.addrs()[0])
    print("Bootstrapping Peer B against Peer A:", peer_a_addr)
    await peer_b.bootstrap([peer_a_addr])

    cid = await peer_a.add_file(__file__)  # adds this script as the demo content
    print("Peer A added file. CID:", cid)

    # Note: no provider_addr argument here on purpose.
    content = await peer_b.get_file(cid)
    print(f"Peer B fetched {len(content)} bytes without being told who has it.")

    assert len(content) > 0

    await peer_b.close()
    await peer_a.close()


if __name__ == "__main__":
    trio.run(main)
