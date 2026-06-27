import hashlib
import logging

import trio

from py_ipfs_lite.config import Config
from py_ipfs_lite.peer import Peer

logging.getLogger("py_ipfs_lite.reprovider").setLevel(logging.WARNING)


async def main():
    print("Demo 8: Verifiable Proofs via Inference Logs")

    print("\nStarting an IPFS Peer...")
    peer = Peer(
        Config(reprovide_interval_seconds=-1), listen_addrs=["/ip4/127.0.0.1/tcp/0"]
    )
    await peer.start()

    print("\n[AI Agent] Performing inference task...")
    prompt = "Summarize the benefits of content-addressed storage."
    response = "Content-addressed storage ensures data immutability and verifiable integrity by identifying data by its cryptographic hash rather than its location."

    print("\n[AI Agent] Constructing verifiable inference log...")
    prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()

    inference_log = {
        "model": "gpt-4o-mini",
        "system_prompt": "You are a helpful assistant.",
        "user_prompt": prompt,
        "prompt_hash": prompt_hash,
        "response": response,
        "timestamp": "2026-06-18T21:05:00Z",
        "agent_signature": "0xABCDEF1234567890",  # Mock signature proving the agent authored this
    }

    print("Inference Log:")
    for k, v in inference_log.items():
        print(f"  {k}: {v}")

    print("\n[IPFS] Storing inference log as an immutable DAG-CBOR node...")
    cid = await peer.add_node(inference_log, codec="dag-cbor")
    print(f"Successfully stored! Proof CID: {cid}")

    print(
        "\n[Verifier] Another party receives the CID and fetches the log to verify it..."
    )
    fetched_log = await peer.get_node(cid)

    print("[Verifier] Verifying data integrity...")
    assert fetched_log == inference_log
    print("Verification passed! The fetched log perfectly matches the original data.")
    print(
        f"\nProof Result: Because the CID ({cid})\nis a direct cryptographic hash of this data, it is mathematically impossible\nfor the response or prompt to have been secretly altered after the fact."
    )

    print("\nClosing the peer cleanly...")
    await peer.close()


if __name__ == "__main__":
    trio.run(main)
