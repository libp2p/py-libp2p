# Production Deployment

This guide covers the configuration knobs, known limitations, and security properties
you need to understand before running `py-ipfs-lite` in a production environment.
It intentionally documents the rough edges — reading this once is better than
discovering them yourself at 2 AM.

---

## Connection Manager Tuning

Every libp2p peer maintains open connections to other peers. Without bounds, long-running
nodes accumulate hundreds or thousands of connections, exhausting file descriptors and
memory. The connection manager enforces two thresholds:

```python
Config(
    conn_mgr_high_water=900,   # start pruning above this many connections
    conn_mgr_low_water=600,    # prune down to this count
)
```

| Field | Default | Meaning |
|---|---|---|
| `conn_mgr_high_water` | `900` | When the open connection count crosses this, the pruner kicks in |
| `conn_mgr_low_water` | `600` | The pruner closes least-recently-used connections until this target is reached |

### Tuning for your environment

**Long-running public-network daemon (default):**
The defaults are sized for a node that participates in DHT routing and accumulates
many ambient connections. 900/600 is conservative — most deployments won't approach it.

**Embedded agent process (resource-constrained):**
Lower both thresholds significantly. A GooseSwarm agent that only connects to a handful
of known peers doesn't need 900 connections:

```python
Config(
    conn_mgr_high_water=50,
    conn_mgr_low_water=25,
)
```

**Offline / local-network only (`offline=True`):**
No DHT bootstrap → far fewer ambient connections. The defaults are fine, but the limits
will rarely be hit.

---

## Bootstrap Peers

### Using the defaults

The `daemon`, `add`, and `get` subcommands all call `peer.bootstrap(DEFAULT_BOOTSTRAP_PEERS)`
automatically after `peer.start()`. The defaults are the official libp2p infrastructure
nodes and are sufficient for connecting to the public IPFS network.

```python
from py_ipfs_lite.cli import DEFAULT_BOOTSTRAP_PEERS

await peer.bootstrap(DEFAULT_BOOTSTRAP_PEERS)
```

### Using your own bootstrap peers

For private or air-gapped networks, replace the defaults entirely:

```python
MY_BOOTSTRAP = [
    "/ip4/10.0.0.1/tcp/4001/p2p/12D3KooW...",
    "/ip4/10.0.0.2/tcp/4001/p2p/12D3KooW...",
]
await peer.bootstrap(MY_BOOTSTRAP)
```

`bootstrap()` is just a `peer.host.connect()` loop — it does not write anything
persistent. If a bootstrap peer is unreachable, the call logs a warning and continues
with the remaining peers. One successful connection is enough to join the DHT.

### Stable PeerID across restarts

Without a seed, a new Ed25519 key pair is generated on every process start. Remote peers
that cached your old PeerID will not be able to dial you by ID after a restart. For
long-running daemons, use a fixed seed:

```bash
uv run py-ipfs-lite daemon --api --seed "my-stable-seed"
```

Or in the SDK:

```python
from libp2p.crypto.ed25519 import create_new_key_pair
import hashlib

seed = hashlib.sha256(b"my-stable-seed").digest()
key_pair = create_new_key_pair(seed=seed)
peer = Peer(Config(), host_key=key_pair, listen_addrs=["/ip4/0.0.0.0/tcp/4001"])
```

The seed is deterministic — the same bytes always produce the same Ed25519 key pair and
therefore the same PeerID.

---

## Timeout Configuration

```python
Config(default_timeout=30.0)   # seconds
```

`default_timeout` is used as the per-operation timeout for:
- DHT `find_providers` during `get_file()` / `get_node()`
- Bitswap block fetch
- IPNS publish and resolve

**30 seconds is generous** for most operations. On the public network, DHT lookups
typically complete in 2–10 seconds. Bitswap fetches from a connected peer are usually
sub-second.

Lower it for latency-sensitive applications:

```python
Config(default_timeout=10.0)
```

Or override per-call:

```python
data = await peer.get_file(cid, timeout=5.0)
value = await peer.resolve_name(peer_id, timeout=15.0)
```

If a timeout is exceeded, `get_file()` and `get_node()` raise `BlockNotFoundError`.
`resolve_name()` raises `RoutingError`.

---

## Known Limitations

These are stated plainly so you can design around them rather than discover them in
production.

### CARv1 only — no CARv2

`export_car()` produces CARv1 with a single root CID. CARv2 (which adds a random-access
index section) is not produced. `import_car()` handles both versions on input.

**Impact:** Tools that specifically require CARv2 (e.g. some `car` CLI subcommands
with `--version=2`) will need to convert. `lotus client import --car` accepts CARv1
without issue.

### IPNS sequence numbers are timestamp-based

Each `publish_name()` call uses the current Unix timestamp (in nanoseconds) as the
sequence number. This means:

- **Two publishes within the same second** will produce the same sequence number.
  DHT nodes receiving both records have no basis to prefer one over the other. The
  effective update may be whichever record propagates last.
- **After a process restart**, sequence numbers resume from the current timestamp,
  which is always higher than any previously published record. Old records are always
  superseded.
- **Sequence numbers carry no semantic meaning** beyond "higher = newer."

**Impact:** Do not publish an IPNS name more than once per second. In practice this
is never a real constraint — IPNS records are designed to be updated on the order of
minutes to hours, not sub-second.

### Upstream `MerkleDag.add_file` blocking I/O

The `add_file()` call ultimately delegates to `MerkleDag.add_file()` in `py-libp2p`,
which performs synchronous blocking file I/O under a global lock. This limits
concurrent ingestion throughput.

**Impact:**
- Concurrent `add_file()` calls share a single effective serialization point.
- The throughput ceiling for `add_node()` (small DAG-JSON/CBOR nodes, no file I/O)
  is ~850 nodes/sec on modern hardware. For file ingestion, throughput is constrained
  by the blocking I/O step.
- This is a `py-libp2p` upstream issue, not a `py-ipfs-lite` design choice.

**Mitigation:**
- For bulk file ingestion workloads, run multiple `py-ipfs-lite` processes (one per
  CPU core) rather than multiple `Peer` instances in one process.
- For DAG node workloads, concurrent `add_node()` is safe and scales well up to the
  throughput ceiling.

### IPNI `provide()` is unauthenticated — by design

`DelegatedHTTPRouting.provide()` is intentionally a no-op. The IPNI protocol requires
authentication (Reframe or signed provider records) to accept provider submissions.
Publishing to IPNI without authentication support is not useful.

**Impact:** CIDs added by `py-ipfs-lite` are announced to the **KadDHT** only, not to
`cid.contact`. If a remote peer uses IPNI exclusively (e.g. a Filecoin SP), it will
not discover your content via IPNI.

**Mitigation:** Use `peer.bootstrap(DEFAULT_BOOTSTRAP_PEERS)` so your peer participates
in the public DHT and CIDs are reachable via DHT lookup.

---

## Security Notes

### What IS verified

| Property | Verification |
|---|---|
| Block integrity on fetch | Every fetched block's bytes are hashed and compared to the expected CID before being returned. Corrupted or tampered blocks are rejected. |
| IPNS record authenticity | `resolve_name()` verifies the Ed25519 V2 signature, checks that the embedded pubkey matches the expected PeerID, and checks the record has not expired. |
| IPNS record freshness | Records past their `validity` timestamp are rejected. |
| Transport confidentiality | All connections use Noise (XX pattern) — traffic is encrypted and authenticated at the transport layer. |

### What is NOT verified

| Property | Explanation |
|---|---|
| IPNI announce-side trust | Any peer can `PUT /routing/v1/providers/{cid}` to IPNI claiming to have any CID. There is no cryptographic link between the announcement and the actual content. **This is closed on the fetch side** — block integrity is always verified against the CID. |
| DHT provider record authenticity | Any peer can write a DHT provider record for any CID. Same mitigation: block integrity check on fetch. |
| Peer reputation | `py-ipfs-lite` has no peer scoring or banning system. A peer that repeatedly sends bad data will time out, but is not banned. |

### SECIO is fully removed

`py-ipfs-lite` supports **Noise only** for transport security. The legacy SECIO
protocol has been removed from `py-libp2p`. If you attempt to connect to a node
that requires SECIO (Kubo < 0.14, 2022 or older), the handshake will fail immediately
with a protocol negotiation error.

Any current Kubo release (0.14+) supports Noise as the preferred transport.

### HTTP API has no authentication

The HTTP API server has no built-in authentication or rate limiting. It is bound to
`127.0.0.1` by default for this reason. **Do not expose the API port to the public
internet** without placing an authenticating reverse proxy (nginx, Caddy, Traefik) in
front of it.

```bash
# Safe: loopback only (default)
uv run py-ipfs-lite daemon --api --api-host 127.0.0.1

# UNSAFE: binds to all interfaces — only use inside a trusted network or behind a proxy
uv run py-ipfs-lite daemon --api --api-host 0.0.0.0
```

---

## Pre-flight Checklist for Production

Before going live, verify:

- [ ] `--seed` is set so the PeerID is stable across restarts
- [ ] `--blockstore-path` points to a volume with sufficient space
- [ ] `--api-host` is `127.0.0.1` unless behind a proxy
- [ ] `conn_mgr_high_water` / `conn_mgr_low_water` are appropriate for your
  connection budget
- [ ] `reprovide_interval_seconds` is set to a value that keeps content discoverable
  (default 12 h is fine for most cases)
- [ ] Process is managed by systemd or equivalent — not a bare terminal session
- [ ] Log output is captured (`> daemon.log 2>&1` or journald)
- [ ] You have read the [Known Limitations](#known-limitations) section above
