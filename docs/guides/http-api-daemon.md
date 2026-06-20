# HTTP API Daemon

This guide explains how to run `py-ipfs-lite` as a long-running daemon with the
Kubo-compatible HTTP API enabled, covers every relevant CLI flag, and shows the API in
action via the two shell examples.

**Relevant examples:**

- [`examples/06_http_api.sh`](../../examples/06_http_api.sh) — start a daemon, then
  exercise add, cat, dag/put, dag/get, pin, and GC via `curl`
- [`examples/07_reprovider.sh`](../../examples/07_reprovider.sh) — watch the background
  Reprovider loop re-announce CIDs to the DHT

**Run them:**

```bash
bash examples/06_http_api.sh
bash examples/07_reprovider.sh
```

For the full list of every endpoint with parameters and response shapes, see the
[HTTP API Reference](../reference/http-api.md).

---

## Starting the Daemon

The simplest form — P2P peer only, no HTTP API:

```bash
uv run py-ipfs-lite daemon
```

With the HTTP API enabled on the default port (5001):

```bash
uv run py-ipfs-lite daemon --api
```

With a persistent identity (same PeerID across restarts):

```bash
uv run py-ipfs-lite daemon --api --seed "my-stable-node-seed"
```

The daemon prints its PeerID and all listening multiaddrs on startup:

```
Starting py-ipfs-lite daemon...
Daemon Peer ID: 12D3KooWHNte...
Listening on 2 address(es):
  /ip4/127.0.0.1/tcp/52323/p2p/12D3KooWHNte...
  /ip4/192.168.1.10/tcp/52323/p2p/12D3KooWHNte...
Daemon is running. Press Ctrl+C to stop...
```

Press **Ctrl-C** to stop cleanly. All background tasks (Reprovider, ConnectionPruner)
are cancelled and the libp2p host is closed.

---

## Daemon Flags

All flags from the [CLI reference](../reference/cli.md) apply. The ones most relevant
to daemon operation:

| Flag | Default | Effect |
|---|---|---|
| `--api` | off | Enable the HTTP API server |
| `--api-host` | `127.0.0.1` | Bind the API to this address. Use `0.0.0.0` to expose externally |
| `--api-port` | `5001` | HTTP API port |
| `--port` | `0` (random) | P2P listening port |
| `--seed` | none | Deterministic PeerID seed — same seed = same identity |
| `--blockstore-type` | `filesystem` | `filesystem` (persistent) or `memory` (ephemeral) |
| `--blockstore-path` | `.py_ipfs_lite/blocks` | Filesystem blockstore directory |
| `--reprovide-interval` | `43200` (12 h) | Seconds between DHT re-announcements. `-1` to disable |
| `--no-ipni` | off | Disable IPNI (cid.contact) routing |
| `--offline` | off | Disable all networking |

---

## Example 06: HTTP API in Action

[`examples/06_http_api.sh`](../../examples/06_http_api.sh)

This script starts a daemon on port 8085 (to avoid clashing with a running Kubo on 5001)
and walks through five operations entirely via `curl`.

### Starting the daemon in the background

```bash
uv run py-ipfs-lite daemon \
  --port 0 \
  --api --api-host 127.0.0.1 --api-port 8085 \
  --blockstore-type filesystem \
  --blockstore-path ./demo_blocks \
  > daemon.log 2>&1 &

DAEMON_PID=$!
trap "kill $DAEMON_PID; rm -f hello.txt daemon.log" EXIT

sleep 3   # wait for the API to start accepting connections
```

### 1 — Add a file

```bash
echo "hello from py-ipfs-lite" > hello.txt
ADD_RESP=$(curl -s -F file=@hello.txt http://127.0.0.1:8085/api/v0/add)
# {"Name":"hello.txt","Hash":"bafkrei...","Size":"24"}

FILE_CID=$(echo $ADD_RESP | grep -o '"Hash":"[^"]*' | grep -o '[^"]*$')
```

### 2 — Fetch it back

```bash
curl -s "http://127.0.0.1:8085/api/v0/cat?arg=$FILE_CID"
# hello from py-ipfs-lite
```

### 3 — Store a DAG-JSON node

```bash
DAG_PUT_RESP=$(curl -s -X POST \
  -H "Content-Type: application/json" \
  -d '{"hello":"world"}' \
  "http://127.0.0.1:8085/api/v0/dag/put?store-codec=dag-json")
# {"Cid":{"/":"bafyrei..."}}

DAG_CID=$(echo $DAG_PUT_RESP | grep -o '"Cid":{"/":"[^"]*' | grep -o '[^"]*$')
```

### 4 — Fetch the DAG node

```bash
curl -s "http://127.0.0.1:8085/api/v0/dag/get?arg=$DAG_CID"
# {"hello":"world"}
```

### 5 — Pin it, then run GC

```bash
# Pin to protect from GC
curl -s -X POST "http://127.0.0.1:8085/api/v0/pin/add?arg=$DAG_CID&recursive=true"
# {"Pins":["bafyrei..."]}

# GC — removes all unpinned blocks
curl -s -X POST "http://127.0.0.1:8085/api/v0/repo/gc"
# {"reclaimed_blocks":0,"retained_blocks":2}
```

The pinned DAG node and the added file both survive GC because they are pinned.

---

## Example 07: The Reprovider Loop

[`examples/07_reprovider.sh`](../../examples/07_reprovider.sh)

The Reprovider is a background task that periodically re-announces all pinned CIDs to
the DHT, keeping them discoverable. DHT provider records have a TTL of ~24 hours; without
re-announcement, remote peers will eventually stop being able to discover your content.

This script sets the interval to 3 seconds (instead of the default 12 hours) to make
the loop observable in a short demo:

```bash
uv run py-ipfs-lite --debug daemon \
  --port 0 \
  --reprovide-interval 3 \
  --blockstore-type filesystem \
  --blockstore-path ./demo_blocks \
  > reprovider.log 2>&1 &

DAEMON_PID=$!
trap "kill $DAEMON_PID; rm -f reprovider.log" EXIT

sleep 10   # let several reprovide cycles run

grep -E "Reproviding.*blocks to the DHT|Finished reproviding" reprovider.log
```

The log output will show lines like:

```
Reproviding 2 blocks to the DHT...
Finished reproviding 2 blocks in 0.42s
Reproviding 2 blocks to the DHT...
Finished reproviding 2 blocks in 0.38s
```

### Reprovider configuration

| `reprovide_interval_seconds` | Behaviour |
|---|---|
| `43200` (default, 12 h) | Suitable for long-running daemons serving public content |
| `3600` (1 h) | More aggressive — useful for high-priority content |
| `-1` | Disabled — content is announced once at `add_file()` time and never again |

**Only pinned blocks are re-announced.** Blocks cached from the network via Bitswap
are not re-announced — only blocks you have explicitly pinned with `add_pin()`.

---

## Running Behind a Process Supervisor

For production deployments, run the daemon under a process supervisor rather than
directly in a terminal.

**systemd example:**

```ini
[Unit]
Description=py-ipfs-lite IPFS daemon
After=network.target

[Service]
ExecStart=uv run py-ipfs-lite daemon \
    --api \
    --api-host 127.0.0.1 \
    --api-port 5001 \
    --seed my-stable-seed \
    --blockstore-path /var/lib/py-ipfs-lite/blocks
Restart=on-failure
RestartSec=5
WorkingDirectory=/opt/py-ipfs-lite

[Install]
WantedBy=multi-user.target
```

**Key points:**
- Use `--seed` so the PeerID is stable across restarts. Without it, a new random key
  pair is generated on every start, and remote peers that cached your old PeerID will
  not find you.
- The `--api-host 127.0.0.1` default is intentional — do **not** expose the API port
  publicly without an authentication proxy in front of it. The API has no built-in
  auth.
- Set `--blockstore-path` to a location with sufficient disk space. The default
  `.py_ipfs_lite/blocks` is relative to the working directory.
