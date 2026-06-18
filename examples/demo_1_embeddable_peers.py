import trio
from py_ipfs_lite.peer import Peer
from py_ipfs_lite.config import Config


async def main():
    peer_a = Peer(Config(reprovide_interval_seconds=-1), listen_addrs=["/ip4/127.0.0.1/tcp/0"])
    peer_b = Peer(Config(reprovide_interval_seconds=-1), listen_addrs=["/ip4/127.0.0.1/tcp/0"])

    await peer_a.start()
    await peer_b.start()

    print("Peer A id:   ", peer_a.host.id())
    print("Peer A addrs:", peer_a.host.addrs())
    print("Peer B id:   ", peer_b.host.id())
    print("Peer B addrs:", peer_b.host.addrs())

    assert peer_a.host.id() != peer_b.host.id()
    assert peer_a._started and peer_b._started

    await peer_b.close()
    await peer_a.close()
    print("Both peers closed cleanly.")


if __name__ == "__main__":
    trio.run(main)
