# P2P Model Checkpoint Sharing over IPFS + libp2p

Peer A trains a model, checkpoints it, and uploads it to IPFS. Peer B —
even if it was offline for the entire time Peer A was training — can
reconnect later, ask "what's the latest?", and pull the checkpoint straight
from IPFS.

```
libp2p  = live communication   (who has what, and where)
IPFS    = persistent storage   (the checkpoint itself)
```

## Overview

The core idea: **never send the model over the wire directly.** Send a
small JSON message over libp2p containing an IPFS CID; let IPFS carry the
actual (potentially large) checkpoint bytes, durably, independent of
whether both peers happen to be online at the same moment.

```
libp2p
   ↓
CID
   ↓
IPFS
   ↓
10 MB model
```

This is what makes offline peer recovery work: Peer A can keep training and
publishing checkpoints 2, 3, 4... while Peer B is completely disconnected.
When B reconnects, it asks A for the latest round, gets back a CID, and
fetches the checkpoint from IPFS — content that's been sitting there the
whole time, independent of A's or B's connection state at any given moment.

## Architecture

```
                        P2P ML NETWORK

             ┌────────────────────────────────┐
             │          libp2p network        │
             │     (CID announcements,        │
             │      sync requests, etc.)      │
             └────────────────────────────────┘
                    │                  │
             ┌──────▼──────┐    ┌──────▼──────┐
             │   PEER A    │    │   PEER B    │
             │ Local Data  │    │ Local Data  │
             │     │       │    │     │       │
             │   Train     │    │   Train     │
             │     │       │    │     │       │
             │ Checkpoint  │    │ Checkpoint  │
             └──────┬──────┘    └──────┬──────┘
                    │                  │
                    ▼                  ▼
               Local IPFS         Local IPFS
                  Node               Node
                    │                  │
                    └────────┬─────────┘
                             ▼
                       IPFS NETWORK
                  (content-addressed checkpoints)
```

## How It Works

The MVP flow, end to end:

1. Peer A trains a simple ML model on its local data shard
2. Peer A saves a checkpoint bundle (model + metadata) to disk
3. Peer A uploads the checkpoint archive to IPFS
4. IPFS returns a CID
5. Peer A sends that CID to Peer B over a libp2p stream (`/ml/checkpoint/1.0.0`)
6. Peer B receives the CID
7. Peer B fetches the checkpoint archive from IPFS by CID
8. Peer B verifies the checkpoint's integrity (hash check)
9. Peer B loads the model
10. Peer B can continue training from there

**Offline recovery** works the same way, just decoupled in time: instead of
B reacting to a live announcement from A, B *asks* A ("what's your latest
round?") whenever it reconnects. If A's answer is a round newer than B's
own, B fetches and adopts it. If A is at or behind B's round, B leaves its
own state alone — **a peer never automatically downgrades**.

### Direct vs IPFS communication

| | Used for |
|---|---|
| **libp2p** (real-time) | CID announcements, sync requests/responses, peer discovery |
| **IPFS** (persistent) | Model checkpoints, metadata, historical versions |

## Requirements

- Python 3.11+
- A running local IPFS (Kubo) daemon — see [Installing IPFS](#installing-ipfs)
- Two terminals (or two machines) to run Peer A and Peer B

## Installing IPFS

Install Kubo (the reference IPFS implementation) and start the daemon:

```bash
# see https://docs.ipfs.tech/install/command-line/ for your platform
ipfs init          # first time only
ipfs daemon        # keep this running in its own terminal
```

By default this project talks to the daemon's HTTP RPC API at
`http://127.0.0.1:5001/api/v0`. Override with `--ipfs-api` or the
`IPFS_API_URL` environment variable if your daemon listens elsewhere.

> **Why not `ipfshttpclient`?** That package pins to a narrow range of
> daemon versions and regularly breaks on current Kubo releases. Kubo's
> HTTP RPC API is stable and simple enough to drive directly with
> `requests` — see `p2p_checkpoint/ipfs_utils.py`.

## Installing Python Dependencies

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Configuration

Copy `.env.example` to `.env` if you want to override defaults (none of
this is required for the local two-peer demo):

```bash
cp .env.example .env
```

## Running Peer A

```bash
python run_peer.py --name peer-a --port 8000 --seed 1 listen
```

This starts a libp2p host, prints its dialable multiaddr(s), and idles,
answering `sync_request` / `checkpoint_request` / `checkpoint_announcement`
messages from any peer that connects. `--seed` pins the peer's libp2p
identity so its address doesn't change between restarts (handy for demos).

## Running Peer B

In a second terminal, connect to Peer A's printed address:

```bash
python run_peer.py --name peer-b --port 8001 --seed 2 sync \
    --connect /ip4/127.0.0.1/tcp/8000/p2p/<peer-a-id>
```

## Training

Each peer trains on its own shard of the Iris dataset (peer-a: 70%,
peer-b: 30%, see `examples/iris_data.py`):

```bash
python run_peer.py --name peer-a --port 8000 --seed 1 train \
    --connect /ip4/127.0.0.1/tcp/8001/p2p/<peer-b-id>
```

Example output:

```
Peer: peer-a (16Uiu2HAm...)
Training on 84 local samples...
Checkpoint saved (round 1).
Uploaded to IPFS -> CID: bafybeigdyr...
Model hash: sha256:c04d6969...
Connecting to 16Uiu2HAm... to announce...
Announcement acknowledged: CheckpointAvailable(checkpoint_id='checkpoint-001', found=False, cid=None)
```

(`found=False` just means the other peer hasn't *fetched* it yet — the
announcement is informational; adopting a checkpoint is always a deliberate
`sync`, never automatic.)

## Checkpointing

A checkpoint is a `model.pkl` + `metadata.json` bundle, archived into
`checkpoint-<round>.tar.gz`:

```
checkpoint-003.tar.gz
├── model.pkl        # joblib-serialized LogisticRegression + light metadata
└── metadata.json    # round, peer_id, dataset, model_type, created_at, model_hash, ...
```

Only that single archive is ever uploaded to or fetched from IPFS — see
`p2p_checkpoint/checkpoint.py`.

## IPFS Storage

`p2p_checkpoint/ipfs_utils.py` wraps three Kubo HTTP RPC endpoints:

- `POST /api/v0/add` — upload + pin a checkpoint archive, get back a CID
- `POST /api/v0/cat` — fetch a checkpoint archive's bytes by CID
- `POST /api/v0/id` / `/version` — daemon health checks

## P2P Synchronization

`p2p_checkpoint/protocol.py` defines a custom libp2p protocol,
`/ml/checkpoint/1.0.0`, with five JSON message types
(`p2p_checkpoint/messages.py`):

- `sync_request` / `sync_response` — "what's your latest round?"
- `checkpoint_announcement` — "I just published a new checkpoint"
- `checkpoint_request` / `checkpoint_available` — ask for one specific round

`p2p_checkpoint/sync.py` implements the actual reconciliation logic: pull a
peer's latest round, compare against local state, fetch + verify + adopt
only if the remote is strictly ahead.

## Offline Peer Recovery

This is the scenario the project exists to demonstrate:

```
A online, training rounds 1, 2, 3, 4 → all pushed to IPFS
B offline the entire time
B comes back online, reconnects to A
B: "what's your latest round?"  →  A: "round 4, cid=bafy..."
B fetches bafy... from IPFS, verifies it, loads it
B is now caught up to round 4, without ever having been online while
rounds 2-4 were being produced.
```

See `tests/test_offline_peer_sync.py` for this exact scenario, automated.

## Testing

```bash
pytest
```

The suite (44 tests) covers model train/predict/save/load, checkpoint
bundling + integrity verification, the IPFS client (against a stubbed HTTP
session, plus an optional test that runs for real if a local daemon is
reachable), message (de)serialization + validation, the libp2p protocol
handlers over real in-process hosts, a full train→checkpoint→IPFS→libp2p→
sync integration flow, and — the most important one — the offline-peer
catch-up scenario above.

No live IPFS daemon or second machine is required to run the tests; an
in-memory fake (`tests/fake_ipfs.py`) stands in for Kubo.

## Example Output

```
$ python run_peer.py --name peer-b --port 8001 sync --connect <peer-a-addr>
Peer: peer-b (16Uiu2HAm...)
Connecting to 16Uiu2HAm...
Syncing...
✓ Downloaded checkpoint from IPFS
✓ Integrity verified
✓ Model loaded

Local model updated: round 1 -> 4 (cid=bafybeigdyr...)
```

## Architecture Diagram

See [Architecture](#architecture) above, and `docs/` (design doc this
implementation was built from) for the fuller diagram set covering
multi-peer topologies, PubSub, and the training-round timeline.

## Limitations

- **No federated aggregation.** Each round replaces the previous local
  model outright; this project does not average weights across peers.
  The MVP explicitly treats "latest checkpoint" as the canonical shared
  state — see `p2p_checkpoint/sync.py` module docstring.
- **No PubSub / multi-peer broadcast yet.** Sync is peer-to-peer (ask one
  specific connected peer). Extending to a `/ml/checkpoints` PubSub topic
  for many-peer fan-out is straightforward on top of the existing protocol
  but out of scope for the MVP.
- **No conflict resolution.** Two peers producing "round 5" from different
  local data are not reconciled — see design notes in `sync.py`.
- **Single-file checkpoints.** Fine for a LogisticRegression; would need
  chunking for genuinely large models.

## Future Work

- libp2p PubSub broadcast (`/ml/checkpoints` topic) for N-peer fan-out
  instead of pairwise `sync`
- Multi-peer demo (A ↔ B ↔ C) with a shared IPFS view
- Federated weight averaging instead of "latest wins"
- A small persisted peer-address book so peers can rediscover each other
  without a hardcoded multiaddr each time

## Project Layout

```
p2p-model-checkpoint/
├── README.md
├── LICENSE
├── requirements.txt
├── pyproject.toml
├── .env.example
├── .gitignore
│
├── p2p_checkpoint/
│   ├── model.py         # LocalModel: sklearn LogisticRegression wrapper
│   ├── checkpoint.py    # bundle/extract checkpoint archives, integrity
│   ├── ipfs_utils.py    # Kubo HTTP API client
│   ├── messages.py      # /ml/checkpoint/1.0.0 wire message schemas
│   ├── protocol.py      # libp2p protocol wiring (RequestResponse)
│   ├── peer.py          # Peer: ties model+checkpoint+ipfs+protocol+db together
│   ├── db.py            # SQLite checkpoint ledger
│   └── sync.py          # pull-based reconciliation, never-downgrade logic
│
├── run_peer.py           # CLI: listen / train / sync / status
│
├── examples/
│   └── iris_data.py      # Iris dataset partitioning for the 2-peer demo
│
└── tests/
    ├── fake_ipfs.py               # in-memory IPFS stand-in for tests
    ├── test_model.py
    ├── test_checkpoint.py
    ├── test_ipfs.py
    ├── test_protocol.py
    ├── test_integration.py
    └── test_offline_peer_sync.py  # the scenario this project is about
```
