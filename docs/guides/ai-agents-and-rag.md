# AI Agents and RAG with py-ipfs-lite

This guide explains why content-addressed storage is a natural fit for AI agent workloads,
then walks through three concrete examples in increasing complexity:

- [Example 08](#example-08-verifiable-inference-your-entry-point) — verifiable inference
  (the simplest entry point)
- [Example 13](#example-13-agent-memory-chain-the-flagship-demo) — a linked conversation
  memory chain (the main conference demo)
- [Example 14](#example-14-distributed-rag-scaling-to-multiple-peers) — distributed
  Retrieval-Augmented Generation across two peers

**Run the examples:**

```bash
uv run python examples/08_verifiable_inference.py
uv run python examples/13_agent_memory_chain.py
uv run python examples/14_distributed_rag.py
```

______________________________________________________________________

## Why Content-Addressing for Agent Memory?

Modern AI agents face a structural problem: their outputs are mutable and unverifiable by
default. A response stored in a database can be overwritten silently. A log file can be
altered after the fact. There is no built-in way to prove that a given response came from a
specific model, a specific prompt, at a specific point in time.

Content-addressing inverts this. When you store a piece of data in IPFS, its address —
the CID — **is** a cryptographic hash of its content. This has three direct consequences
for agent memory:

1. **Immutability:** Once a memory node has a CID, the data it represents cannot change.
   If you want to update a memory, you create a new node with a new CID. The old node stays
   exactly as it was. This creates an append-only audit trail by construction.

1. **Tamper-evidence:** You do not need to trust the storage medium. Anyone holding a CID
   can verify the data they receive against it. If the data has been tampered with, the
   hash will not match.

1. **Addressability across peers:** Because CIDs are content-derived, two peers that
   independently store the same data will generate the same CID. This is what makes
   distributed RAG possible — the retriever can fetch a chunk by CID from any peer that
   has it, and verify it locally without trusting the peer.

For the AI Agent agent framework, these properties directly address the grant milestone
requirement: a verifiable, auditable, tamper-evident record of agent reasoning that can be
exported for archival or handed off to Filecoin storage.

______________________________________________________________________

## Example 08: Verifiable Inference — Your Entry Point

[`examples/08_verifiable_inference.py`](../../examples/08_verifiable_inference.py)

This is the simplest demonstration of the core idea: store an inference event as a DAG-CBOR
node and prove that neither the prompt nor the response was altered after the fact.

### What it does

An "agent" constructs a structured inference log — the model used, the system prompt, the
user prompt, the response, and an agent signature — then stores it as a single DAG-CBOR
node.

```python
import trio
import hashlib
from py_ipfs_lite.peer import Peer
from py_ipfs_lite.config import Config

async def main():
    peer = Peer(Config(reprovide_interval_seconds=-1), listen_addrs=["/ip4/127.0.0.1/tcp/0"])
    await peer.start()

    prompt = "Summarize the benefits of content-addressed storage."
    response = "Content-addressed storage ensures data immutability..."

    inference_log = {
        "model": "gpt-4o-mini",
        "system_prompt": "You are a helpful assistant.",
        "user_prompt": prompt,
        "prompt_hash": hashlib.sha256(prompt.encode()).hexdigest(),
        "response": response,
        "timestamp": "2026-06-18T21:05:00Z",
        "agent_signature": "0xABCDEF1234567890",
    }

    # Store it — returns a CID that IS the hash of this exact data
    cid = await peer.add_node(inference_log, codec="dag-cbor")
    print(f"Proof CID: {cid}")

    # Any party with the CID can fetch and verify
    fetched_log = await peer.get_node(cid)
    assert fetched_log == inference_log  # mathematical guarantee
    print("Verification passed!")

    await peer.close()

trio.run(main)
```

### Why DAG-CBOR?

DAG-CBOR (CBOR-encoded IPLD) is used here instead of DAG-JSON for two reasons:

- **Deterministic encoding:** DAG-CBOR has a canonical byte representation, which means
  the same Python dict will always produce the same CID. This is essential for the
  verification property.
- **Efficiency:** CBOR is more compact than JSON for binary and numeric data.

### The verification guarantee

The assertion `fetched_log == inference_log` is backed by the CID itself. `peer.get_node(cid)`
fetches the raw bytes, verifies they hash to `cid`, then deserializes them. If the bytes have
been tampered with, they will not hash to the expected CID and the fetch will fail. The
equality check is a semantic sanity check on top of the cryptographic guarantee.

______________________________________________________________________

## Example 13: Agent Memory Chain — The Flagship Demo

[`examples/13_agent_memory_chain.py`](../../examples/13_agent_memory_chain.py)

This is the most important example in this guide for a conference or grant audience. It
demonstrates a **linked conversation memory chain**: each turn of an agent conversation
is stored as an IPLD DAG-CBOR node, and each node contains a `"prev"` link (as an IPLD
CID link) pointing to the prior turn. The result is a hash-linked chain — structurally
identical to a blockchain — where every turn is immutable and every link is cryptographically
verified.

### The chain structure

```
Turn 1 (user)          Turn 2 (agent)         Turn 3 (user)          Turn 4 (agent)
┌─────────────┐        ┌─────────────┐        ┌─────────────┐        ┌─────────────┐
│ role: user  │◄───────│ role: agent │◄───────│ role: user  │◄───────│ role: agent │
│ text: ...   │  prev  │ text: ...   │  prev  │ text: ...   │  prev  │ text: ...   │
│ text_hash:  │        │ text_hash:  │        │ text_hash:  │        │ text_hash:  │
│ timestamp:  │        │ timestamp:  │        │ timestamp:  │        │ timestamp:  │
│ prev: null  │        │ prev: {CID1}│        │ prev: {CID2}│        │ prev: {CID3}│
│ CID: bafyA  │        │ CID: bafyB  │        │ CID: bafyC  │        │ CID: bafyD  │
└─────────────┘        └─────────────┘        └─────────────┘        └─────────────┘
                                                                      ← chain head
```

Only the **chain head CID** needs to be shared or stored externally. Anyone who has it can
traverse the entire history backwards through the `"prev"` links and verify each node's
integrity along the way.

### Full walkthrough

```python
import trio
import hashlib
import datetime
from py_ipfs_lite.peer import Peer
from py_ipfs_lite.config import Config

async def main():
    peer = Peer(
        Config(reprovide_interval_seconds=-1, blockstore_type="memory"),
        listen_addrs=["/ip4/127.0.0.1/tcp/0"]
    )
    await peer.start()

    turns = [
        ("user",  "What is content-addressed storage?"),
        ("agent", "Content-addressed storage identifies data by a hash of its content..."),
        ("user",  "How does IPFS use it?"),
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
            # IPLD CID link: {"/": "<cid-string>"} is the standard IPLD link notation
            "prev": {"/": prev_cid} if prev_cid else None,
        }
        cid = await peer.add_node(node, codec="dag-cbor")
        cids.append(cid)
        prev_cid = cid
        print(f"  [{role}] → CID: {cid[:30]}...")

    print(f"\nChain head: {cids[-1]}")
```

### Verifying chain integrity by traversal

Given only the chain head CID, the full conversation can be reconstructed and verified:

```python
    print("\nVerifying chain integrity by traversal...")
    current_cid = cids[-1]  # start from the head
    chain = []

    while current_cid:
        node = await peer.get_node(current_cid)
        chain.append((node["role"], node["text"][:50]))
        link = node.get("prev")
        current_cid = link["/"] if link else None  # follow the IPLD link

    chain.reverse()  # oldest turn first
    for role, text in chain:
        print(f"  [{role}]: {text}...")

    print(f"\n✓ Chain of {len(chain)} turns verified — immutable and content-addressed")
    await peer.close()

trio.run(main)
```

### Why this matters for AI Agent / grant compliance

This pattern directly addresses several audit and compliance requirements:

- **Non-repudiation:** The agent cannot retroactively claim it gave a different answer.
  The CID of each turn is a mathematical commitment to that turn's content.
- **Tamper detection:** Modifying any turn's text changes its hash, which changes its CID,
  which invalidates the `"prev"` link in the following node. The chain breaks detectably.
- **Minimal external trust:** The only thing that needs to be shared externally is the
  chain head CID — a single string. Anyone with that CID can independently reconstruct
  and verify the full history.
- **Portability:** The chain can be exported as a CAR file (see the
  [CAR files guide](./car-files-and-filecoin.md)) and submitted to Filecoin for
  long-term verifiable archival.

______________________________________________________________________

## Example 14: Distributed RAG — Scaling to Multiple Peers

[`examples/14_distributed_rag.py`](../../examples/14_distributed_rag.py)

This example scales the single-node concept to a two-peer setup: an **Indexer** peer
indexes document chunks into IPLD, and a separate **Retriever** peer fetches and queries
them by CID via direct Bitswap connection. This is the foundation of a decentralised
Retrieval-Augmented Generation pipeline.

### Architecture

```
  Indexer Peer                           Retriever Peer
  ┌─────────────────────────────┐        ┌──────────────────────────────────┐
  │                             │        │                                  │
  │  doc-0 ──► chunk_cid_0 ─┐  │        │  fetch(index_cid, indexer_addr)  │
  │  doc-1 ──► chunk_cid_1 ─┤  │        │      │                           │
  │  doc-2 ──► chunk_cid_2 ─┘  │        │      ▼                           │
  │                 │           │        │  index_node { chunks: [cid0..] } │
  │                 ▼           │        │      │                           │
  │         index_cid           │─Bitswap►      ▼                           │
  │  (root DAG-CBOR node)       │        │  fetch each chunk by CID         │
  │                             │        │  score for relevance             │
  └─────────────────────────────┘        │  assemble RAG context            │
                                         └──────────────────────────────────┘
```

### Setting up the Indexer

```python
import trio
from py_ipfs_lite.peer import Peer
from py_ipfs_lite.config import Config

async def main():
    indexer = Peer(
        Config(reprovide_interval_seconds=-1, blockstore_type="memory"),
        listen_addrs=["/ip4/127.0.0.1/tcp/0"]
    )
    await indexer.start()

    documents = [
        "IPFS is a distributed file system that seeks to connect all computing devices...",
        "Filecoin is a decentralized storage network built on IPFS with economic incentives...",
        "libp2p is a modular networking framework used in IPFS, Ethereum 2.0, and Polkadot...",
    ]

    # Each document chunk is stored as a DAG-CBOR node
    chunk_links = []
    for i, doc in enumerate(documents):
        chunk_cid = await indexer.add_node({"text": doc, "source": f"doc-{i}"}, codec="dag-cbor")
        chunk_links.append({"/": chunk_cid})  # IPLD link notation

    # A root index node links to all chunks
    index_cid = await indexer.add_node(
        {"type": "rag-index", "chunks": chunk_links},
        codec="dag-cbor"
    )
    print(f"Root Index CID: {index_cid}")
    # Share just this one CID with the Retriever
```

### Setting up the Retriever

```python
    retriever = Peer(
        Config(reprovide_interval_seconds=-1, blockstore_type="memory"),
        listen_addrs=["/ip4/127.0.0.1/tcp/0"]
    )
    await retriever.start()

    indexer_addr = str(indexer.host.addrs()[0])  # the indexer's multiaddr

    # Fetch the root index by CID directly from the Indexer peer
    index = await retriever.get_node(index_cid, provider_addr=indexer_addr)

    query = "How does Filecoin relate to IPFS?"

    # Fetch and score each chunk
    results = []
    for chunk_link in index["chunks"]:
        chunk = await retriever.get_node(chunk_link["/"], provider_addr=indexer_addr)
        score = sum(w in chunk["text"].lower() for w in query.lower().split())
        results.append((score, chunk["text"], chunk_link["/"]))

    results.sort(reverse=True, key=lambda x: x[0])

    # The top-K chunks form the RAG context for the LLM call
    context = "\n".join(text for _, text, _ in results[:2])
    print(f"RAG Context:\n{context}")

    await retriever.close()
    await indexer.close()

trio.run(main)
```

### Key points

- **`provider_addr=indexer_addr`** bypasses DHT discovery and connects directly to the
  Indexer peer. In a production deployment, you would use DHT discovery and let the
  retriever find providers by CID.
- **The retriever verifies each chunk** implicitly — `peer.get_node(cid)` always checks
  that the received bytes hash to the expected CID. A malicious or corrupted peer cannot
  serve false content without detection.
- **The index CID is a stable handle** to the entire document corpus. You can publish it
  via IPNS to make it mutable (see the [IPNS guide](./ipns.md)), allowing the corpus to
  grow while still being addressable by a fixed name.

______________________________________________________________________

## Bringing It Together: The Full Agent Stack

The three examples compose into a complete, verifiable agent memory system:

| Layer                   | Example    | What it provides                             |
| ----------------------- | ---------- | -------------------------------------------- |
| Single inference record | Example 08 | Tamper-evident proof of one model call       |
| Conversation chain      | Example 13 | Linked, ordered history of a full session    |
| Distributed retrieval   | Example 14 | Multi-peer RAG over content-addressed chunks |
| Mutable registry        | Example 15 | IPNS name pointing to the current chain head |
| Long-term archival      | Example 19 | CAR export → Filecoin storage                |

For the next step, see the [CAR Files and Filecoin guide](./car-files-and-filecoin.md) to
learn how to export a conversation chain as a single portable CAR file and submit it to
the Filecoin network.
