# HTTP API Reference

`py-ipfs-lite` exposes a Kubo-compatible HTTP API when run as a daemon. Endpoints follow
Kubo's `/api/v0` convention so existing tooling (scripts, clients, dashboards) works
without modification.

**Start the daemon:**

```bash
uv run py-ipfs-lite daemon --api --api-port 5001
```

**Base URL:** `http://127.0.0.1:5001`

**Total endpoints:** 17

______________________________________________________________________

## Error Responses

All errors return JSON with a `"detail"` field:

```json
{"detail": "Block not found for CID: bafy..."}
```

| HTTP Status | Condition                          |
| ----------- | ---------------------------------- |
| `404`       | Block, pin, or IPNS name not found |
| `500`       | Internal error                     |
| `503`       | Peer not started                   |

______________________________________________________________________

## Root

### `GET /api/v0/id` · `POST /api/v0/id`

Returns this node's identity information.

**Response:**

```json
{
  "ID": "12D3KooWHNte...",
  "Addresses": [
    "/ip4/127.0.0.1/tcp/52323/p2p/12D3KooWHNte..."
  ]
}
```

**Example:**

```bash
curl http://127.0.0.1:5001/api/v0/id
```

______________________________________________________________________

### `GET /api/v0/version` · `POST /api/v0/version`

Returns the node version.

**Response:**

```json
{
  "Version": "0.1.0",
  "Commit": "",
  "System": "py-ipfs-lite"
}
```

**Example:**

```bash
curl http://127.0.0.1:5001/api/v0/version
```

______________________________________________________________________

## Files

### `POST /api/v0/add`

Adds a file to the local blockstore and announces it to the DHT / IPNI.

**Request:** `multipart/form-data` with a `file` field.

**Response:**

```json
{
  "Name": "test.txt",
  "Hash": "bafkreihdwdcefgh4dqkjv67uzcmw7ojee6xedzdetojuzjevtenxquvyku",
  "Size": "42"
}
```

**Example:**

```bash
curl -X POST -F "file=@test.txt" http://127.0.0.1:5001/api/v0/add
```

______________________________________________________________________

### `GET /api/v0/cat` · `POST /api/v0/cat`

Streams the content of a file by CID.

**Query params:**

| Param | Required | Description              |
| ----- | -------- | ------------------------ |
| `arg` | ✅       | CID of the file to fetch |

**Response:** `application/octet-stream` — raw file bytes streamed.

**Example:**

```bash
curl "http://127.0.0.1:5001/api/v0/cat?arg=bafkrei..." --output file.txt
```

______________________________________________________________________

## DAG

### `POST /api/v0/dag/put`

Stores a generic IPLD DAG node.

**Query params:**

| Param         | Required | Default    | Description                          |
| ------------- | -------- | ---------- | ------------------------------------ |
| `store-codec` | ❌       | `dag-json` | Codec to use: `dag-json`, `dag-cbor` |

**Request body:** JSON-encoded node data.

**Response:**

```json
{
  "Cid": {"/": "bafyreihdwdcefgh4dqkjv67uzcmw7ojee6xedzdetojuzjevtenxquvyku"}
}
```

**Example:**

```bash
curl -X POST \
  "http://127.0.0.1:5001/api/v0/dag/put?store-codec=dag-cbor" \
  -H "Content-Type: application/json" \
  -d '{"title": "Hello World", "author": "py-ipfs-lite"}'
```

______________________________________________________________________

### `GET /api/v0/dag/get` · `POST /api/v0/dag/get`

Fetches and decodes a DAG node by CID.

**Query params:**

| Param | Required | Description                  |
| ----- | -------- | ---------------------------- |
| `arg` | ✅       | CID of the DAG node to fetch |

**Response:** The decoded node as JSON.

```json
{"title": "Hello World", "author": "py-ipfs-lite"}
```

**Example:**

```bash
curl "http://127.0.0.1:5001/api/v0/dag/get?arg=bafyrei..."
```

______________________________________________________________________

## Blocks

### `POST /api/v0/block/stat`

Returns the size of a raw block stored locally. Returns `404` if not found.

**Query params:**

| Param | Required | Description      |
| ----- | -------- | ---------------- |
| `arg` | ✅       | CID of the block |

**Response:**

```json
{"Key": "bafkrei...", "Size": 512}
```

**Example:**

```bash
curl -X POST "http://127.0.0.1:5001/api/v0/block/stat?arg=bafkrei..."
```

______________________________________________________________________

### `POST /api/v0/block/rm`

Removes a raw block from the local blockstore. Does not check pins.

**Query params:**

| Param | Required | Description                |
| ----- | -------- | -------------------------- |
| `arg` | ✅       | CID of the block to remove |

**Response:**

```json
{"Hash": "bafkrei...", "Error": ""}
```

**Example:**

```bash
curl -X POST "http://127.0.0.1:5001/api/v0/block/rm?arg=bafkrei..."
```

______________________________________________________________________

## Pins

### `POST /api/v0/pin/add`

Pins a CID to protect it from garbage collection.

**Query params:**

| Param       | Required | Default | Description                            |
| ----------- | -------- | ------- | -------------------------------------- |
| `arg`       | ✅       | —       | CID to pin                             |
| `recursive` | ❌       | `true`  | Pin the CID and all blocks it links to |

**Response:**

```json
{"Pins": ["bafyrei..."]}
```

**Example:**

```bash
# Recursive pin (default)
curl -X POST "http://127.0.0.1:5001/api/v0/pin/add?arg=bafyrei..."

# Direct pin only (root block only)
curl -X POST "http://127.0.0.1:5001/api/v0/pin/add?arg=bafyrei...&recursive=false"
```

______________________________________________________________________

### `POST /api/v0/pin/rm`

Removes a pin. The block becomes eligible for GC on the next `/api/v0/repo/gc` call.

**Query params:**

| Param | Required | Description  |
| ----- | -------- | ------------ |
| `arg` | ✅       | CID to unpin |

**Response:**

```json
{"Pins": ["bafyrei..."]}
```

**Example:**

```bash
curl -X POST "http://127.0.0.1:5001/api/v0/pin/rm?arg=bafyrei..."
```

______________________________________________________________________

## Refs

### `POST /api/v0/refs/local`

Lists all CIDs in the local blockstore.

**Response:**

```json
{
  "Refs": [
    {"Ref": "bafyrei...", "Err": ""},
    {"Ref": "bafkrei...", "Err": ""}
  ]
}
```

**Example:**

```bash
curl -X POST http://127.0.0.1:5001/api/v0/refs/local
```

______________________________________________________________________

## Repo

### `POST /api/v0/repo/gc`

Runs a garbage collection pass. Deletes all blocks that are not reachable from a pinned
root.

**Response:**

```json
{
  "reclaimed_blocks": 12,
  "retained_blocks": 47
}
```

**Example:**

```bash
curl -X POST http://127.0.0.1:5001/api/v0/repo/gc
```

______________________________________________________________________

### `GET /api/v0/repo/stat` · `POST /api/v0/repo/stat`

Returns statistics about the local blockstore.

**Response:**

```json
{
  "NumObjects": 59,
  "RepoSize": 2097152,
  "RepoPath": ".py_ipfs_lite/blocks",
  "Version": "1"
}
```

**Example:**

```bash
curl http://127.0.0.1:5001/api/v0/repo/stat
```

______________________________________________________________________

### `GET /api/v0/repo/version` · `POST /api/v0/repo/version`

Returns the current repo version number. Used for detecting schema compatibility.

> **Note:** `py-ipfs-lite` detects the on-disk version but does not perform automatic
> repo migration. If the version is unexpected, inspect and handle manually.

**Response:**

```json
{"Version": "1"}
```

**Example:**

```bash
curl http://127.0.0.1:5001/api/v0/repo/version
```

______________________________________________________________________

## Swarm

### `GET /api/v0/swarm/peers` · `POST /api/v0/swarm/peers`

Lists all currently connected peers.

**Response:**

```json
{
  "Peers": [
    {
      "Peer": "12D3KooW...",
      "Addr": "/ip4/192.168.1.10/tcp/4001",
      "Direction": 0
    }
  ]
}
```

**Example:**

```bash
curl http://127.0.0.1:5001/api/v0/swarm/peers
```

______________________________________________________________________

## Name (IPNS)

### `POST /api/v0/name/publish`

Publishes an IPNS record for this node's PeerID pointing to `arg`.

**Query params:**

| Param | Required | Description                                        |
| ----- | -------- | -------------------------------------------------- |
| `arg` | ✅       | The IPFS path to publish (e.g. `/ipfs/bafyrei...`) |

**Response:**

```json
{
  "Name": "12D3KooWHNte...",
  "Value": "/ipfs/bafyrei..."
}
```

**Example:**

```bash
curl -X POST "http://127.0.0.1:5001/api/v0/name/publish?arg=/ipfs/bafyrei..."
```

______________________________________________________________________

### `GET /api/v0/name/resolve` · `POST /api/v0/name/resolve`

Resolves an IPNS name (PeerID) to its current value. Performs full cryptographic
validation (signature + expiry check).

**Query params:**

| Param | Required | Description                       |
| ----- | -------- | --------------------------------- |
| `arg` | ✅       | PeerID string to resolve (base58) |

**Response:**

```json
{"Path": "/ipfs/bafyrei..."}
```

**Example:**

```bash
curl "http://127.0.0.1:5001/api/v0/name/resolve?arg=12D3KooWHNte..."
```

______________________________________________________________________

## Observability

### `GET /debug/metrics/prometheus`

Exposes all Prometheus metrics in text exposition format. Compatible with any Prometheus
scrape config or Grafana datasource.

**Response:** `text/plain; version=0.0.4` (Prometheus text format)

```
# HELP ipfs_blockstore_size_bytes Total size of blocks in the blockstore
# TYPE ipfs_blockstore_size_bytes gauge
ipfs_blockstore_size_bytes 2097152.0
# HELP ipfs_blockstore_blocks_total Total number of blocks in the blockstore
...
```

**Example:**

```bash
curl http://127.0.0.1:5001/debug/metrics/prometheus
```

**Prometheus scrape config:**

```yaml
scrape_configs:
  - job_name: py-ipfs-lite
    static_configs:
      - targets: ["127.0.0.1:5001"]
    metrics_path: /debug/metrics/prometheus
```

For the full list of exposed metrics and what they mean, see the
[Observability guide](../guides/observability.md) *(coming in Phase 3)*.
