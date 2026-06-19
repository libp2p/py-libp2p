import trio
import hashlib
import datetime
from py_ipfs_lite.peer import Peer
from py_ipfs_lite.config import Config

async def main():
    peer = Peer(Config(reprovide_interval_seconds=-1, blockstore_type="memory"), listen_addrs=["/ip4/127.0.0.1/tcp/0"])
    await peer.start()

    print("=== Example 13: Verifiable AI Agent Memory Chain (IPLD DAG) ===")
    turns = [
        ("user", "What is content-addressed storage?"),
        ("agent", "Content-addressed storage identifies data by a hash of its content..."),
        ("user", "How does IPFS use it?"),
        ("agent", "IPFS assigns every file and data structure a CID derived from its content hash..."),
    ]

    prev_cid = None
    cids = []
    for role, text in turns:
        node = {
            "role": role,
            "text": text,
            "text_hash": hashlib.sha256(text.encode()).hexdigest(),
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "prev": {"/": prev_cid} if prev_cid else None,
        }
        cid = await peer.add_node(node, codec="dag-cbor")
        cids.append(cid)
        prev_cid = cid
        print(f"  [{role}] → CID: {cid[:30]}...")

    print(f"\nChain head: {cids[-1]}")
    print("\nVerifying chain integrity by traversal...")
    current_cid = cids[-1]
    chain = []
    while current_cid:
        node = await peer.get_node(current_cid)
        chain.append((node["role"], node["text"][:50]))
        link = node.get("prev")
        current_cid = link["/"] if link else None
        
    chain.reverse()
    for role, text in chain:
        print(f"  [{role}]: {text}...")
    print(f"\n✓ Chain of {len(chain)} turns verified — immutable and content-addressed")
    await peer.close()

if __name__ == "__main__":
    trio.run(main)
