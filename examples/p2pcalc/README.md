# P2PCalc : Decentralised EtherCalc over py-libp2p GossipSub

**Author:** Dashpreet Singh

**Email:** dashpreetsinghhanda@gmail.com | 2024ucs0087@iitjammu.ac.in

**Institution:** IIT Jammu, B.Tech CSE 2024-2028

**Issue:** [DMP 2026 #34](https://github.com/seetadev/py-libp2p/issues/34)

______________________________________________________________________

## What this is

P2PCalc replaces EtherCalc's centralised Redis pub-sub synchronisation layer
with py-libp2p GossipSub. Multiple peers can collaboratively edit the same
spreadsheet in real time , no central server, no single point of failure,
no cloud dependency.

The browser-facing EtherCalc UI and the Node.js worker are completely
untouched. P2PCalc intercepts at the Redis pub-sub layer, the only place
where EtherCalc's components talk to each other. Everything else stays the
same.

______________________________________________________________________

## The problem with EtherCalc's current architecture

EtherCalc works by having a central Node.js server relay SocialCalc command
strings between browser clients over WebSockets. Every edit goes:

```
Browser A -> WebSocket -> Node.js server -> Redis pub-sub -> Node.js server -> WebSocket -> Browser B
```

This architecture has three hard problems:

**Single point of failure.** If the server goes down, collaboration stops.
Peers with pending edits lose them.

**No offline-first capability.** A peer that loses connectivity cannot
continue editing and reconnect later. There is no mechanism to reconcile
diverged states.

**Centralised trust.** All edits pass through one server. In civic-tech,
disaster response, or low-connectivity rural deployments, this is a
fundamental constraint not an incidental one.

______________________________________________________________________

## The approach

The key insight from studying EtherCalc's internals is that the server
does not compute, it just relays. Every SocialCalc command is executed
client-side in the browser's JavaScript engine. The server is a glorified
message bus.

If we can replace that message bus with a decentralised one, we get
peer-to-peer collaboration for free, with no changes to the UI or the
client-side computation engine.

EtherCalc uses Redis pub-sub channels internally, one per room, with the
channel name `sc:<room_name>`. Every command string (`set A1 value 42`,
`insertrow 3 1`, etc.) is published to this channel and consumed by the
Node.js worker which relays it to connected browsers.

P2PCalc taps into this channel. The adapter subscribes to `sc:<room_name>`,
wraps each command in a typed operation envelope, and broadcasts it via
GossipSub to all other peers on the topic `p2pcalc/<room_name>`. Incoming
operations from remote peers are unwrapped and injected back into the same
Redis channel. EtherCalc's existing Socket.io layer delivers them to
browsers as if they came from a local user.

```
Before (centralised):
  Browser -> WS -> Node.js -> Redis -> Node.js -> WS -> Browser

After (P2PCalc):
  Browser -> WS -> Node.js -> Redis -> P2PCalc Adapter
                                            |
                                       GossipSub topic
                                       p2pcalc/<room>
                                            |
                                   Remote P2PCalc Adapter
                                            |
                              Redis -> Node.js -> WS -> Browser
```

The browser never knows the difference.

______________________________________________________________________

## Innovations

### 1. Hybrid Logical Clocks instead of wall clocks

Most collaborative editors that claim to handle concurrent edits use wall-clock
timestamps for ordering. This is quietly broken. Two peers on different
machines will have clocks that drift. A peer editing offline and reconnecting
will have a stale wall-clock reading. Under partition, last-write-wins with
wall clocks silently corrupts data.

P2PCalc uses Hybrid Logical Clocks (HLC), introduced by Kulkarni et al. (2014).
HLC combines physical time (for human-readable timestamps) with a logical
counter (for causal ordering when physical clocks agree). The result: causally
consistent operation ordering across peers without requiring any clock
synchronisation protocol. Two operations from the same peer are always ordered
correctly. Two operations from different peers are ordered by causality when
it exists, and by a deterministic tiebreaker (peer_id) when it does not.

Every operation carries an HLC timestamp. Every receiving peer updates its
local clock from incoming operations. The invariant is maintained globally
without any coordinator.

### 2. Multi-Value Register for cell conflicts

Naive last-write-wins is the wrong model for collaborative spreadsheets.
Consider: Alice and Bob both edit cell A1 simultaneously. Under LWW, one
edit silently disappears with no notification to either user. This is data
loss disguised as a feature.

P2PCalc implements a Multi-Value Register (MVR) for cell-level conflict
resolution. The MVR tracks all concurrent versions of a cell, those for
which neither version causally precedes the other. When concurrent writes
exist, the cell is marked as a conflict and all competing values are
preserved as candidates. A conflict marker is injected into the spreadsheet
as a comment cell adjacent to the conflicted cell, showing all competing
values. The user can then explicitly resolve which value should win.

This is the same model Git uses for merge conflicts: preserve all
concurrent edits, surface them to the user, require explicit resolution.
No data is ever silently lost.

A write that causally follows all existing versions (higher HLC) automatically
resolves any existing conflict by dominating all candidates. This covers
the common case where one peer's edit observes and incorporates the
conflict before writing.

Three conflict policies are available:

- `mvr` (default): Multi-Value Register, explicit conflict markers
- `lww`: Last-Write-Wins using HLC, no conflict markers, fast
- `peer`: Deterministic peer-priority (lowest peer_id always wins), useful
  for testing and offline-first workflows where one device is authoritative

### 3. Replicated Growable Array for structural operations

Cell-value CRDTs are well understood. Row and column insertions and deletions
are harder. Consider: peer A inserts a row at position 3. Peer B simultaneously
deletes row 3. Which row 3 does B mean? The original row 3, or the row that A
just created?

Operational Transformation (OT) systems handle this with transformation
functions that rewrite operations against each other. OT is notoriously
difficult to implement correctly, and the transformation functions for
spreadsheet structural operations have known correctness issues.

P2PCalc uses a Replicated Growable Array (RGA) for row and column structure.
RGA tracks the intent of each structural operation rather than its absolute
effect. Concurrent insertions at the same position are deterministically
ordered using peer_id as a tiebreaker, so all peers converge to the same
structural order without coordination. Deletions use tombstones so that
concurrent edits targeting a deleted row can still be applied without
crashing, the deleted row is marked invisible but its position in the
sequence is preserved for conflict resolution.

### 4. Causal buffering for out-of-order delivery

GossipSub provides best-effort delivery in an eventually-consistent network.
Operations may arrive out of order, particularly after a peer reconnects or
joins late. Applying operations out of causal order corrupts the CRDT state.

P2PCalc attaches causal dependency tracking to each operation: every
operation records the op_id of the last operation the issuing peer had
observed on that sheet. The adapter maintains a causal buffer. When an
operation arrives whose declared dependencies have not yet been seen, it is
held in the buffer rather than applied immediately. When the missing
dependency arrives, the buffer is flushed in dependency order.

This gives P2PCalc causal consistency guarantees on top of GossipSub's
eventual delivery, without requiring a vector clock or a full dependency
graph.

### 5. Two-phase late-joiner state sync

When a new peer joins a sheet, it needs the current state. Replaying the
full operation log from the beginning is impractical for long-lived
sessions.

P2PCalc uses a two-phase approach. On joining, the peer broadcasts a
`SNAPSHOT_REQUEST` operation via GossipSub. Any peer that has state
responds with `SNAPSHOT_CHUNK` operations containing the current cell
state serialised as JSON, chunked into 64KB pieces for libp2p stream
compatibility. The joining peer assembles the chunks and applies the
snapshot.

Multiple peers may respond simultaneously. P2PCalc selects the response
with the highest operation count (most history) as authoritative. If
counts are equal, the lower peer_id is preferred, ensuring a deterministic
choice without coordination.

After the snapshot is applied, the joining peer replays any operations
that arrived after the snapshot was taken, using the `op_log_from` field
embedded in the snapshot to know where to start.

### 6. Local op-log WAL for crash recovery

P2PCalc persists each operation to a local write-ahead log (WAL) as it is
applied. The WAL uses a 4-byte length-prefixed MessagePack format, the same
encoding used on the wire.

On restart after a crash, a peer replays its local WAL to recover its last
known state before requesting a network snapshot. This has two benefits:
recovery does not require other peers to be online, and the snapshot request
only needs to cover the delta since the local log's last entry rather than
the full session history.

This mirrors how distributed databases (CockroachDB, etcd) use WAL-based
recovery to survive crashes without full resync.

### 7. MessagePack over JSON

Every operation is serialised with MessagePack rather than JSON. For
spreadsheet collaboration, operations are small and frequent, a busy
editing session may produce tens of operations per second per peer.

MessagePack is approximately 30-40% smaller than equivalent JSON and 2-3x
faster to encode and decode in Python benchmarks. Over GossipSub, smaller
messages reduce mesh bandwidth consumption and allow the heartbeat interval
to be shortened (currently 1 second rather than the GossipSub default of 2
seconds) without saturating the network, which directly reduces the latency
between an edit and its propagation to other peers.

### 8. Operation integrity verification

Every operation includes a SHA-256 content hash of its key fields (sheet_id,
raw_command, peer_id, op_id). The receiving adapter verifies this hash before
applying the operation. Operations that fail verification are silently
discarded, providing a lightweight integrity guarantee against accidental
corruption or malformed messages from buggy peers.

The GossipSub message validator hook is used to reject operations that fail
integrity checks at the pub-sub layer, before they are delivered to the
application. This prevents malformed operations from being forwarded to
other peers in the mesh.

______________________________________________________________________

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  EtherCalc (unchanged)                                  │
│  Browser <-> WebSocket <-> Node.js worker               │
└───────────────────────┬─────────────────────────────────┘
                        │  Redis pub-sub (sc:<room>)
                        │
┌───────────────────────┴─────────────────────────────────┐
│  P2PCalc Adapter  (adapter.py)                          │
│                                                         │
│  Redis channel subscriber    Redis channel publisher    │
│  (reads local edits)         (injects remote edits)     │
│          │                           ▲                  │
│          ▼                           │                  │
│  OperationFactory             Operation.from_bytes()    │
│  (parse SocialCalc command)   (deserialise)             │
│          │                           │                  │
│          ▼                           │                  │
│  SheetCRDT.apply()           CausalBuffer               │
│  (local optimistic apply)    (hold until deps arrive)   │
│          │                           │                  │
└──────────┼───────────────────────────┼──────────────────┘
           │  GossipSub publish        │  GossipSub subscribe
           ▼                           │
┌──────────────────────────────────────┴──────────────────┐
│  py-libp2p GossipSub v2.0  (p2p_node.py)               │
│                                                         │
│  Topic: p2pcalc/<room_name>                             │
│  Peer discovery: mDNS (LAN) / DHT (WAN)                │
│  Transport: TCP / WebSocket / QUIC                      │
│  Security: Noise protocol                               │
│  Mux: Yamux                                             │
└─────────────────────────────────────────────────────────┘
           │  mesh propagation to all peers
           ▼
    [Remote P2PCalc peers — same stack]
```

______________________________________________________________________

## File structure

```
examples/p2pcalc/
├── README.md               this file
├── requirements.txt
├── p2pcalc/
│   ├── __init__.py
│   ├── operation.py        operation encoding, HLC, MessagePack protocol
│   ├── crdt.py             MVR + RGA CRDT implementations
│   ├── adapter.py          EtherCalc Redis <-> GossipSub bridge
│   ├── p2p_node.py         libp2p host, GossipSub v2.0, state sync
│   ├── state_sync.py       snapshot assembly, op-log WAL persistence
│   └── main.py             CLI entrypoint
└── tests/
    ├── __init__.py
    └── test_p2pcalc.py     42 unit tests (no network or Redis required)
```

______________________________________________________________________

## Quick start

### Prerequisites

- Python 3.10+
- Redis running locally: `redis-server`
- EtherCalc running locally: `npm install -g ethercalc && ethercalc`

### Install

```bash
cd examples/p2pcalc
pip install -r requirements.txt
```

### Run two peers on the same machine

Terminal 1:

```bash
python -m p2pcalc.main --room my-sheet --port 4001
# Output includes: /ip4/127.0.0.1/tcp/4001/p2p/<peer_id>
```

Terminal 2 (paste the multiaddr from Terminal 1):

```bash
python -m p2pcalc.main --room my-sheet --port 4002 \
  --peer /ip4/127.0.0.1/tcp/4001/p2p/<peer_id>
```

Open `http://localhost:8000/my-sheet` in two browser windows. Edits in
either window propagate to the other via GossipSub with no central server.

### Run across machines on a LAN

mDNS peer discovery is active by default. Both machines must be on the
same subnet. Start P2PCalc on each machine with the same `--room` name
and no `--peer` flag. Peers will discover each other automatically.

### Multiple rooms on one node

```bash
python -m p2pcalc.main --room room-a --room room-b --port 4001
```

Each room gets its own GossipSub topic and Redis channel subscription.

### Conflict resolution mode

```bash
# Multi-Value Register (default), surfaces concurrent conflicts as cell markers
python -m p2pcalc.main --room my-sheet --conflict-policy mvr

# Last-Write-Wins, faster, silent data loss on concurrent edits
python -m p2pcalc.main --room my-sheet --conflict-policy lww
```

### Debug logging

```bash
python -m p2pcalc.main --room my-sheet --debug
```

______________________________________________________________________

## Run tests

No network, Redis, or EtherCalc required.

```bash
cd examples/p2pcalc
python -m pytest tests/test_p2pcalc.py -v
# Expected: 42 passed
```

Test coverage includes HLC monotonicity and causal ordering, operation
parsing for all SocialCalc command types, MessagePack serialisation
roundtrip, integrity verification, MVR conflict detection and resolution,
RGA concurrent structural operation merging, SheetCRDT deduplication and
op-log, snapshot assembly and race resolution, and multi-peer convergence
simulation.

______________________________________________________________________

## What is not yet implemented

- DHT-based WAN peer discovery (mDNS only covers LAN today)
- IPFS snapshot storage for durable shared state
- Benchmarking harness comparing latency against centralised EtherCalc
- WebRTC transport for browser-to-browser operation (no Python needed)

These are planned for subsequent PRs in the DMP 2026 timeline.

______________________________________________________________________

## References

- Kulkarni et al., "Logical Physical Clocks and Consistent Snapshots in
  Globally Distributed Databases", 2014 (HLC)
- Shapiro et al., "Conflict-Free Replicated Data Types", INRIA 2011 (CRDT)
- Roh et al., "Replicated Abstract Data Types: Building Blocks for
  Collaborative Applications", 2011 (RGA)
- Tan et al., "From SocialCalc to EtherCalc", AOSA Volume 2, 2012
  (EtherCalc internals and Redis pub-sub architecture)
- libp2p GossipSub v1.1 spec: https://github.com/libp2p/specs/tree/master/pubsub/gossipsub
