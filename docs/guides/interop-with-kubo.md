# Interoperability with Kubo

This guide explains what protocol-level compatibility between `py-ipfs-lite` and
[Kubo](https://github.com/ipfs/kubo) (the reference Go-based IPFS daemon) actually
means, and walks through two concrete examples proving it works in both directions.

**Relevant examples:**

- [`examples/09_kubo_interop.py`](../../examples/09_kubo_interop.py) — simple two-way
  exchange with a live Kubo daemon via the `ipfs` CLI
- [`examples/20_kubo_round_trip.py`](../../examples/20_kubo_round_trip.py) — the
  full round-trip demo using both DAG-JSON and UnixFS DAG-PB (the flagship interop demo)

**Prerequisites:** A running Kubo daemon on localhost port 5001.

```bash
# Install Kubo: https://docs.ipfs.tech/install/command-line/
ipfs daemon
```

**Run the examples:**

```bash
uv run python examples/09_kubo_interop.py
uv run python examples/20_kubo_round_trip.py
```

______________________________________________________________________

## What Protocol Compatibility Actually Means

"Kubo-compatible" is a claim worth unpacking precisely. There are four layers where
compatibility is required, and `py-ipfs-lite` satisfies all of them:

| Layer               | Protocol                            | Status                          |
| ------------------- | ----------------------------------- | ------------------------------- |
| Transport           | TCP + Noise handshake               | ✅ Noise-only (no legacy SECIO) |
| Stream multiplexing | Yamux                               | ✅ Yamux                        |
| Content exchange    | Bitswap 1.2.0                       | ✅ Verified against Kubo        |
| DAG codecs          | DAG-PB (UnixFS), DAG-JSON, DAG-CBOR | ✅ All three verified           |

> **SECIO is not supported.** SECIO is a legacy transport security protocol removed
> from Kubo in v0.14.0. `py-ipfs-lite` uses Noise exclusively. If you are connecting to
> a very old IPFS node (pre-2022) that has SECIO-only configured, the handshake will
> fail. Any current Kubo release supports Noise.

### The upstream PR that proves it

The Bitswap improvements that enable Kubo interoperability — including correct codec
negotiation for DAG-PB, DAG-JSON, and DAG-CBOR — were developed as part of this project
and merged into the canonical `libp2p/py-libp2p` repository via
[PR #1321](https://github.com/libp2p/py-libp2p/pull/1321):

> *"Merge pull request #1321 from sumanjeet0012/improvement/bitswap —
> feat: Bitswap improvements for Kubo compatibility"*

This is verifiable on GitHub. The interop work is now part of the reference Python
libp2p implementation — not a private fork.

______________________________________________________________________

## Example 09: Simple Kubo Interop

[`examples/09_kubo_interop.py`](../../examples/09_kubo_interop.py)

This is the simpler of the two examples. It uses the `ipfs` CLI subprocess to let Kubo
participate, making the mechanics easy to follow.

### What it does

1. Starts a `py-ipfs-lite` peer with DHT enabled (so Kubo can find it)
1. Adds a test file from Python — gets a CID
1. Connects the local Kubo daemon directly to the Python peer's multiaddr
1. Asks Kubo to fetch the CID — Kubo uses Bitswap to pull the block from Python
1. Adds a file from Kubo — gets a different CID
1. Asks the Python peer to fetch that CID — Python uses Bitswap to pull from Kubo

```python
import trio
from py_ipfs_lite.peer import Peer
from py_ipfs_lite.config import Config

async def main():
    peer = Peer(
        Config(reprovide_interval_seconds=10),
        listen_addrs=["/ip4/127.0.0.1/tcp/0"]
    )
    await peer.start()

    # Python adds a file — generates a CID
    py_cid = await peer.add_file("/tmp/test.txt")
    print(f"Python CID: {py_cid}")

    # Get the Python peer's listening multiaddr for Kubo to connect to
    py_addr = str(peer.host.addrs()[0])
    print(f"Python addr: {py_addr}")

    # Kubo connects and fetches via Bitswap
    res = await trio.run_process(
        ["ipfs", "swarm", "connect", py_addr],
        capture_stdout=True, capture_stderr=True
    )
    cat_res = await trio.run_process(
        ["ipfs", "cat", py_cid],
        capture_stdout=True, capture_stderr=True
    )
    print(f"Kubo fetched: {cat_res.stdout.decode().strip()}")

    # Kubo adds a file — Python fetches it back
    add_res = await trio.run_process(
        ["ipfs", "add", "-Q", "/tmp/kubo_test.txt"],
        capture_stdout=True, capture_stderr=True
    )
    kubo_cid = add_res.stdout.decode().strip()
    data = await peer.get_file(kubo_cid)
    print(f"Python fetched: {data.decode().strip()}")

    await peer.close()

trio.run(main)
```

______________________________________________________________________

## Example 20: Full Round-Trip Demo — The Flagship

[`examples/20_kubo_round_trip.py`](../../examples/20_kubo_round_trip.py)

This is the definitive interop proof. Instead of shelling out to the CLI, it establishes
a **direct libp2p connection** between `py-ipfs-lite` and Kubo at the protocol level, then
verifies two-way Bitswap exchange using two different DAG codecs.

### Architecture

```
py-ipfs-lite (Python)                    Kubo (Go)
┌──────────────────────────┐             ┌──────────────────────────┐
│                          │             │                          │
│  Phase 1:                │             │                          │
│  add_node(dag-json) ─────┼──Bitswap───►│  /api/v0/dag/get        │
│  → py_cid               │             │  → reads Python's block  │
│                          │             │                          │
│  Phase 2:                │             │                          │
│  get_file(kubo_cid) ◄────┼──Bitswap────┤  /api/v0/add (UnixFS)  │
│  → kubo payload          │             │  → kubo_cid             │
│                          │             │                          │
└──────────────────────────┘             └──────────────────────────┘
           │                                          │
           └──────── Direct libp2p Noise/Yamux ───────┘
```

### Full walkthrough

```python
import trio
import httpx
import json
from py_ipfs_lite.peer import Peer
from py_ipfs_lite.config import Config
from libp2p.peer.peerinfo import info_from_p2p_addr
from multiaddr import Multiaddr

KUBO_API = "http://127.0.0.1:5001/api/v0"

async def main():
    # Step 1: Discover Kubo's PeerID and local address via its HTTP API
    async with httpx.AsyncClient() as client:
        resp = await client.post(f"{KUBO_API}/id", timeout=2.0)
        kubo_info = resp.json()

    kubo_peer_id = kubo_info["ID"]
    kubo_local_addr = next(
        a for a in kubo_info["Addresses"]
        if "/ip4/127.0.0.1/tcp/" in a
    )
    print(f"Kubo Peer ID: {kubo_peer_id}")

    # Step 2: Start py-ipfs-lite in offline mode (DHT not needed for direct connect)
    config = Config(offline=True, blockstore_type="memory", use_ipni=False)
    peer = Peer(config, listen_addrs=["/ip4/127.0.0.1/tcp/0"])
    await peer.start()

    # Step 3: Establish a direct libp2p connection (Noise handshake + Yamux)
    maddr = Multiaddr(kubo_local_addr)
    kubo_peer_info = info_from_p2p_addr(maddr)
    await peer.host.connect(kubo_peer_info)
    print("✅ Direct libp2p connection established")

    async with httpx.AsyncClient() as client:
        # --- PHASE 1: Python writes DAG-JSON, Kubo reads via Bitswap ---
        py_payload = {"source": "py-ipfs-lite", "message": "Hello Kubo!"}
        py_cid = await peer.add_node(py_payload, codec="dag-json")
        print(f"Python DAG-JSON CID: {py_cid}")

        # Kubo fetches the block from Python over Bitswap
        resp = await client.post(f"{KUBO_API}/dag/get?arg={py_cid}", timeout=5.0)
        kubo_data = resp.json()
        print(f"✅ Kubo fetched via Bitswap: {kubo_data}")

        # --- PHASE 2: Kubo writes UnixFS (DAG-PB), Python reads via Bitswap ---
        kubo_payload = "Hello Python, this is Kubo via UnixFS DAG-PB!"
        files = {"file": ("hello.txt", kubo_payload.encode())}
        resp = await client.post(f"{KUBO_API}/add?cid-version=1", files=files)
        kubo_cid = json.loads(resp.text.strip().split("\n")[-1])["Hash"]
        print(f"Kubo UnixFS CID: {kubo_cid}")

        # Python fetches from Kubo over Bitswap — handles DAG-PB/UnixFS decoding
        data = await peer.get_file(kubo_cid, provider_addr=kubo_local_addr)
        print(f"✅ Python fetched via Bitswap: '{data.decode()}'")

    await peer.close()

trio.run(main)
```

### What the successful output looks like

```
Kubo Peer ID: 12D3KooW...
✅ Direct libp2p connection established

Python DAG-JSON CID: bafyreig...
✅ Kubo fetched via Bitswap: {"message": "Hello Kubo!", "source": "py-ipfs-lite"}

Kubo UnixFS CID: bafkrei...
✅ Python fetched via Bitswap: 'Hello Python, this is Kubo via UnixFS DAG-PB!'
```

### Key implementation points

**Why `offline=True` for the py-ipfs-lite peer?**
When connecting directly to a known peer's multiaddr, DHT bootstrap is unnecessary and
adds latency. Setting `offline=True` disables the KadDHT entirely. The Bitswap exchange
still works because it operates over direct libp2p connections — DHT is only used for
*discovering* peers you don't already know.

**`provider_addr=kubo_local_addr` in `get_file()`**
By supplying the provider's multiaddr directly, we bypass the provider lookup step in
`get_file()`. The peer connects directly to Kubo and issues a Bitswap WANT for the CID.
This makes the demo deterministic — no DHT propagation delay.

**DAG-PB / UnixFS decoding**
When Kubo adds a file via `/api/v0/add`, it stores it as a UnixFS DAG-PB tree. Python's
`get_file()` handles the full DAG-PB → UnixFS → raw bytes decoding internally, including
multi-chunk files. The caller receives the reconstructed file bytes directly.

______________________________________________________________________

## Reproducing the Interop Tests

The `interop/` directory contains the automated test scripts used during development:

| Script                                                               | What it tests                                  |
| -------------------------------------------------------------------- | ---------------------------------------------- |
| [`interop/run_kubo_interop.sh`](../../interop/run_kubo_interop.sh)   | Full Kubo ↔ Python exchange                    |
| [`interop/run_py_py_interop.sh`](../../interop/run_py_py_interop.sh) | Python peer ↔ Python peer exchange             |
| [`interop/py_peer.py`](../../interop/py_peer.py)                     | Standalone Python peer for the interop scripts |

To reproduce:

```bash
# Ensure Kubo daemon is running
ipfs daemon &

# Run the interop suite
bash interop/run_kubo_interop.sh
```

______________________________________________________________________

## Common Issues

### Handshake fails immediately

**Cause:** The remote node may be running an old version of IPFS that uses SECIO.
`py-ipfs-lite` supports Noise only. Check `ipfs version` on the remote — upgrade to
any Kubo release from 2022 or later.

### Kubo fetches the CID but returns an error

**Cause:** Usually a codec mismatch. If Python stored the data as `dag-cbor` but Kubo
is trying to decode it as `dag-pb`, the response will be malformed. Ensure you use
consistent codecs on both sides. For file content, use `peer.add_file()` (which
produces DAG-PB / UnixFS, the native Kubo format).

### `get_file()` hangs waiting for the block

**Cause:** The two peers are not connected. Check that either:

- `provider_addr` is set correctly (direct connect path), or
- Both peers have bootstrapped to the public DHT and the CID has been announced

If you see `Failed to find providers for {cid} in DHT` in the logs, the CID has not
been announced yet. For local testing, always use `provider_addr` for reliability.

### Python peer's address shows `0.0.0.0`

**Cause:** The listening address was bound to `0.0.0.0` but the interface address was
not resolved. Use `peer.host.addrs()[0]` to get the actual announced multiaddr.
