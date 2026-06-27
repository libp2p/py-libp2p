import logging

import trio

from py_ipfs_lite.config import Config
from py_ipfs_lite.peer import Peer

logging.getLogger("py_ipfs_lite.reprovider").setLevel(logging.WARNING)


async def main():
    print("Demo 3: Structured data as an IPLD node (inference-log shape)")
    print("\nStarting an IPFS Peer...")
    peer = Peer(
        Config(reprovide_interval_seconds=-1), listen_addrs=["/ip4/127.0.0.1/tcp/0"]
    )
    await peer.start()

    print(f"Peer initialized with Peer ID: {peer.host.id()}")
    print(f"Listening on multiaddr: {peer.host.addrs()[0]}")

    log_entry = {
        "agent": "summarizer-agent-01",
        "model": "claude-sonnet-4-6",
        "prompt_hash": "bafy...exampleprompthash",
        "timestamp": "2026-06-18T12:00:00Z",
    }

    print("\nPreparing to store the following structured Python dictionary:")
    print(log_entry)

    print("\nEncoding dictionary into IPLD using 'dag-cbor' codec...")
    cid = await peer.add_node(log_entry, codec="dag-cbor")
    print(f"Successfully stored! CID: {cid}")

    print("\nFetching the structured data back from the blockstore using the CID...")
    fetched = await peer.get_node(cid)
    print("Fetched result:")
    print(fetched)

    print(
        "\nVerifying that the fetched data perfectly matches the original dictionary..."
    )
    assert fetched == log_entry
    print("Assertion passed! Data integrity maintained.")

    print("\nClosing the peer cleanly...")
    await peer.close()


if __name__ == "__main__":
    trio.run(main)
