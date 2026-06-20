# CAR Files and Filecoin

This guide covers Content Addressable aRchive (CAR) files: what they are, how to produce
and consume them with `py-ipfs-lite`, and how they connect to the Filecoin storage network.

**Relevant examples:**

- [`examples/11_car_export_import.py`](../../examples/11_car_export_import.py) — basic
  DAG export and offline import
- [`examples/19_filecoin_pipeline.py`](../../examples/19_filecoin_pipeline.py) — full
  GooseSwarm inference trace → CAR → Filecoin pipeline (the flagship grant-relevant demo)

**Run them:**

```bash
uv run python examples/11_car_export_import.py
uv run python examples/19_filecoin_pipeline.py
```

---

## What Is a CAR File?

A CAR (Content Addressable aRchive) file is a flat binary format for packaging an IPLD
Merkle DAG — a root CID plus all the blocks it links to — into a single portable file.

Think of it like a `.tar` for content-addressed data:

| tar | CAR |
|---|---|
| Groups files into one archive | Groups IPLD blocks into one archive |
| Uses filesystem paths as identifiers | Uses CIDs as identifiers |
| No integrity checking | Every block is addressed by its own hash |
| No schema | CARv1 header declares the root CID(s) |

CAR files are the **standard interchange format between IPFS and Filecoin**. When you want
to submit a DAG to a Filecoin storage provider using tools like
[`lotus`](https://lotus.filecoin.io/) or
[`web3.storage`](https://web3.storage/), you hand them a `.car` file.

### CARv1 format (what py-ipfs-lite produces)

```
┌──────────────────────────────────────────────────────────────┐
│  varint(header_len)                                          │
│  CBOR header: { "version": 1, "roots": [<root_cid>] }       │
├──────────────────────────────────────────────────────────────┤
│  For each block in DAG traversal order:                      │
│    varint(len(cid_bytes) + len(block_data))                  │
│    cid_bytes                                                 │
│    block_data                                                │
└──────────────────────────────────────────────────────────────┘
```

> **Current scope:** `py-ipfs-lite` produces and consumes **CARv1 with a single root
> CID**. CARv2 (which adds an index section) and multi-root CARs are not currently
> supported. This is a deliberate scope choice — CARv1 is what Filecoin storage
> providers expect via `lotus client import --car`.

---

## Example 11: Basic Export and Offline Import

[`examples/11_car_export_import.py`](../../examples/11_car_export_import.py)

This example shows the core CAR workflow: build a DAG, export it, then import it into
a completely fresh, offline peer and verify it is identical.

### Building and exporting a DAG

```python
import trio
import os
import tempfile
from py_ipfs_lite.peer import Peer
from py_ipfs_lite.config import Config

async def main():
    car_path = os.path.join(tempfile.gettempdir(), "book.car")

    # Writer peer — builds the DAG in memory
    writer = Peer(
        Config(reprovide_interval_seconds=-1, blockstore_type="memory"),
        listen_addrs=["/ip4/127.0.0.1/tcp/0"]
    )
    await writer.start()

    # Build a simple linked DAG
    leaf_a = await writer.add_node({"content": "chapter one"}, codec="dag-cbor")
    leaf_b = await writer.add_node({"content": "chapter two"}, codec="dag-cbor")
    root = await writer.add_node(
        {"title": "My Book", "chapters": [{"/": leaf_a}, {"/": leaf_b}]},
        codec="dag-cbor"
    )
    print(f"Root CID: {root}")

    # Export the entire DAG (root + all linked blocks) to a single .car file
    await writer.export_car(root, car_path)
    print(f"Exported {os.path.getsize(car_path)} bytes to {car_path}")

    await writer.close()
```

`export_car()` performs a breadth-first traversal of the DAG starting from the root CID,
collecting every block, and writing them sequentially into the CAR file. You do not need
to manually enumerate the blocks — the traversal is automatic regardless of DAG depth or
branching factor.

### Importing on a fresh offline peer

```python
    # Reader peer — fully offline, no network access needed
    reader = Peer(
        Config(offline=True, reprovide_interval_seconds=-1, blockstore_type="memory"),
        listen_addrs=["/ip4/127.0.0.1/tcp/0"]
    )
    await reader.start()

    # import_car returns the list of root CIDs declared in the CAR header
    imported_roots = await reader.import_car(car_path)
    imported_root = imported_roots[0]

    # The root CID is deterministic — same data always yields the same CID
    assert imported_root == root  # will always pass

    # Traverse the imported DAG locally, no network required
    book = await reader.get_node(root)
    print(f"'{book['title']}' with {len(book['chapters'])} chapters")

    await reader.close()

trio.run(main)
```

The `import_car()` call reads the CAR file, writes each block into the local blockstore,
and returns the root CIDs from the header. After import, any `get_node()` or `get_file()`
call for a CID in the CAR will be served entirely from local storage — no network access,
no Bitswap exchange.

---

## Example 19: GooseSwarm Filecoin Pipeline — The Flagship Demo

[`examples/19_filecoin_pipeline.py`](../../examples/19_filecoin_pipeline.py)

This is the most grant-relevant example in the repository. It demonstrates the complete
pipeline from AI agent inference → IPLD DAG → CAR export → Filecoin storage, running
entirely in-process with no external daemon required.

This directly satisfies ProPGF Milestone M1: *"Python IPFS node capable of natively
producing Filecoin-ready CARv1 payloads from agent inference traces."*

### The pipeline

```
AI Agent Inference Steps
        │
        ▼
  IPLD Merkle DAG (dag-json nodes, each linking to the previous step)
        │                   step_1_cid ◄── step_2_cid ◄── step_3_cid ◄── root_cid
        ▼
  peer.export_car(root_cid, "agent_inference_trace.car")
        │
        ▼
  agent_inference_trace.car   (CARv1, self-contained, ~729 bytes for a 4-step trace)
        │
        ▼
  lotus client import --car agent_inference_trace.car
        │
        ▼
  Filecoin Storage Deal  →  verifiable, long-term archival
```

### Full walkthrough

```python
import trio
import os
import logging
from py_ipfs_lite.peer import Peer
from py_ipfs_lite.config import Config

logging.basicConfig(level=logging.INFO, format="%(message)s")

async def main():
    # Step 1: Start a fully offline, in-memory peer
    # No disk storage, no DHT, no IPNI — just the local blockstore
    config = Config(offline=True, blockstore_type="memory", use_ipni=False)
    peer = Peer(config, listen_addrs=["/ip4/127.0.0.1/tcp/0"])
    await peer.start()

    try:
        # Step 2: Log each inference step as a DAG-JSON node
        # Each node links back to the previous step via an IPLD CID link
        step_1_cid = await peer.add_node({
            "type": "user_prompt",
            "content": "What is the weather in Tokyo?"
        }, codec="dag-json")

        step_2_cid = await peer.add_node({
            "type": "tool_call",
            "tool": "get_weather",
            "args": {"location": "Tokyo"},
            "previous_step": {"/": step_1_cid}   # IPLD link to step 1
        }, codec="dag-json")

        step_3_cid = await peer.add_node({
            "type": "tool_result",
            "result": "Heavy Rain",
            "previous_step": {"/": step_2_cid}
        }, codec="dag-json")

        root_cid = await peer.add_node({
            "type": "agent_response",
            "content": "It is currently raining heavily in Tokyo.",
            "previous_step": {"/": step_3_cid}
        }, codec="dag-json")

        print(f"Root CID: {root_cid}")

        # Step 3: Export the entire linked DAG to a single CAR file
        car_filename = "agent_inference_trace.car"
        await peer.export_car(root_cid, car_filename)

        size = os.path.getsize(car_filename)
        print(f"✅ Created {car_filename} ({size} bytes)")
        print(f"Run: lotus client import --car {car_filename}")

    finally:
        await peer.close()
        if os.path.exists(car_filename):
            os.remove(car_filename)

trio.run(main)
```

### What the output looks like

```
Root CID: bafyreig...
✅ Created agent_inference_trace.car (729 bytes)
Run: lotus client import --car agent_inference_trace.car
```

A real 4-step trace produces a ~729 byte CAR file. This scales linearly with the number
of steps and the payload size of each node.

### Why dag-json instead of dag-cbor here?

Example 19 uses `dag-json` (as opposed to Example 13's `dag-cbor`) to make the intermediate
nodes human-readable for debugging and audit purposes. Both codecs are fully supported by
`export_car()` and by Filecoin storage providers. Use `dag-cbor` for production pipelines
where payload compactness matters.

### Submitting to Filecoin

Once you have the `.car` file, standard Filecoin tooling takes over:

**Using Lotus (full node):**
```bash
lotus client import --car agent_inference_trace.car
# Returns a DataCID — use this to make a storage deal
lotus client deal <DataCID> <miner_address> <price> <duration>
```

**Using web3.storage (no node required):**
```bash
w3 up --car agent_inference_trace.car
```

**Using Estuary or other pinning services:**
Most services accept CARv1 uploads via their HTTP API.

---

## API Reference

### `await peer.export_car(cid_str, output_path)`

Traverses the DAG rooted at `cid_str` and writes all blocks to `output_path` as a CARv1
file. Uses `trio.open_file()` internally — the write is fully non-blocking and will not
stall the event loop even for large DAGs.

| Parameter | Type | Description |
|---|---|---|
| `cid_str` | `str` | The root CID to export from |
| `output_path` | `str` | Path to write the `.car` file to |

### `await peer.import_car(input_path)`

Reads a CARv1 file and writes all its blocks into the local blockstore. Returns the list
of root CIDs declared in the CAR header.

| Parameter | Type | Description |
|---|---|---|
| `input_path` | `str` | Path to the `.car` file to import |
| **Returns** | `list[str]` | Root CID strings from the CAR header |

---

## Known Limitations

- **CARv1 only:** `py-ipfs-lite` does not produce or consume CARv2 (which adds an index
  section for random-access). CARv1 is what `lotus client import --car` expects, and is
  sufficient for all current Filecoin storage workflows.
- **Single root:** The `export_car()` function exports from a single root CID. Multi-root
  CARs (which are valid in the spec) are not produced. `import_car()` correctly handles
  multi-root CARs on input and returns all root CIDs.
- **In-memory traversal:** The full DAG is traversed in-memory during export. For
  extremely large DAGs (millions of blocks), peak memory usage during the traversal will
  be proportional to the queue depth, not the total data size.

For the next step in the agent pipeline, see the [IPNS guide](./ipns.md) to learn how to
publish a mutable pointer to your CAR's root CID so the latest version of an inference
trace is always discoverable by a stable name.
