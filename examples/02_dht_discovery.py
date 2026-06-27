import logging

import trio

from py_ipfs_lite.config import Config
from py_ipfs_lite.peer import Peer

logging.getLogger("py_ipfs_lite.reprovider").setLevel(logging.WARNING)


async def main():
    print("Demo 2: DHT discovery by CID alone...")
    print("\nStarting 2 peers...")
    peer_a = Peer(
        Config(reprovide_interval_seconds=-1), listen_addrs=["/ip4/127.0.0.1/tcp/0"]
    )
    peer_b = Peer(
        Config(reprovide_interval_seconds=-1), listen_addrs=["/ip4/127.0.0.1/tcp/0"]
    )

    await peer_a.start()
    await peer_b.start()

    print(
        f"Peer A has Peer ID {peer_a.host.id()}\nmultiaddr: {peer_a.host.addrs()[0]}\n"
    )
    print(f"Peer B has Peer ID {peer_b.host.id()}\nmultiaddr: {peer_b.host.addrs()[0]}")

    peer_a_addr = str(peer_a.host.addrs()[0])
    print(f"\nConnecting Peer B to Peer A using multiaddr: {peer_a_addr}")
    await peer_b.bootstrap([peer_a_addr])
    print("Peers connected successfully.")

    print("\nAdding current file to Peer A's blockstore...")
    cid = await peer_a.add_file(__file__)  # adds this script as the demo content
    print(f"Peer A added file. CID: {cid}")

    # Note: no provider_addr argument here on purpose.
    print(
        "\nRequesting file by CID from Peer B (without providing Peer A's address)..."
    )
    content = await peer_b.get_file(cid)
    print(f"Peer B fetched {len(content)} bytes without being told who has it.")

    assert len(content) > 0

    print("\nClosing both peers cleanly...")
    await peer_b.close()
    await peer_a.close()


if __name__ == "__main__":
    trio.run(main)
