import trio
from py_ipfs_lite.peer import Peer
from py_ipfs_lite.config import Config


async def main():
    peer = Peer(Config(reprovide_interval_seconds=-1), listen_addrs=["/ip4/127.0.0.1/tcp/0"])
    await peer.start()

    log_entry = {
        "agent": "summarizer-agent-01",
        "model": "claude-sonnet-4-6",
        "prompt_hash": "bafy...exampleprompthash",
        "timestamp": "2026-06-18T12:00:00Z",
    }

    cid = await peer.add_node(log_entry, codec="dag-cbor")
    print("Stored inference log as a dag-cbor node. CID:", cid)

    fetched = await peer.get_node(cid)
    print("Fetched back:", fetched)

    assert fetched == log_entry

    await peer.close()


if __name__ == "__main__":
    trio.run(main)
