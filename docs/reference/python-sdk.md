# Python SDK Reference

Complete reference for the `py-ipfs-lite` Python SDK. This page covers every public
method, class, and exception. For narrative walkthroughs that show these in context,
see the [guides](../guides/).

______________________________________________________________________

## `Peer`

The central object. All IPFS operations go through `Peer`.

**Import:**

```python
from py_ipfs_lite.peer import Peer
```

### Constructor

```python
Peer(
    config: Config,
    *,
    host: Host | None = None,
    routing: Routing | None = None,
    datastore: Datastore | None = None,
    blockstore: BlockStore | None = None,
    exchange: Exchange | None = None,
    dag_service: DagService | None = None,
    host_key: KeyPair | None = None,
    listen_addrs: list[str] | None = None,
)
```

All keyword-only arguments after `config` are optional. Any subsystem left as `None` is
automatically constructed during `peer.start()` using the defaults from `config`.

| Parameter      | Type                 | Description                                                                   |
| -------------- | -------------------- | ----------------------------------------------------------------------------- |
| `config`       | `Config`             | Node configuration (see [Config](#config))                                    |
| `host`         | `Host \| None`       | Custom libp2p host. Default: auto-constructed with Noise + Yamux              |
| `routing`      | `Routing \| None`    | Custom routing. Default: `TieredRouting` (KadDHT + IPNI if `use_ipni=True`)   |
| `blockstore`   | `BlockStore \| None` | Custom blockstore. Default: filesystem or memory per `config.blockstore_type` |
| `exchange`     | `Exchange \| None`   | Custom Bitswap exchange. Default: `BitswapClient`                             |
| `dag_service`  | `DagService \| None` | Custom DAG service. Default: `MerkleDag`                                      |
| `host_key`     | `KeyPair \| None`    | Node's Ed25519 identity key. Default: randomly generated each run             |
| `listen_addrs` | `list[str] \| None`  | Multiaddrs to listen on. Example: `["/ip4/0.0.0.0/tcp/4001"]`                 |

### Lifecycle

______________________________________________________________________

#### `await peer.start()`

Initialises all subsystems and starts background tasks (Reprovider, ConnectionPruner).
Must be called before any other method. Calling `start()` on an already-started peer is a
no-op.

```python
peer = Peer(Config(), listen_addrs=["/ip4/127.0.0.1/tcp/0"])
await peer.start()
```

______________________________________________________________________

#### `await peer.close()`

Gracefully stops all background tasks, closes the Bitswap exchange, and closes the
libp2p host. Safe to call multiple times.

```python
await peer.close()
```

______________________________________________________________________

#### `await peer.bootstrap(peers)`

Connects to a list of bootstrap peers and joins the DHT network.

| Parameter | Type        | Description                                                                   |
| --------- | ----------- | ----------------------------------------------------------------------------- |
| `peers`   | `list[str]` | List of multiaddr strings (e.g. `/ip4/104.131.131.82/tcp/4001/p2p/QmaCpD...`) |

```python
from py_ipfs_lite.cli import DEFAULT_BOOTSTRAP_PEERS
await peer.bootstrap(DEFAULT_BOOTSTRAP_PEERS)
```

______________________________________________________________________

### File Operations

______________________________________________________________________

#### `await peer.add_file(path_or_stream, params=None, timeout=None, progress_callback=None) → str`

Chunks a file into blocks, builds a UnixFS DAG-PB tree, writes all blocks to the local
blockstore, and announces the root CID to the DHT / IPNI.

| Parameter           | Type                                 | Default                  | Description                                                |
| ------------------- | ------------------------------------ | ------------------------ | ---------------------------------------------------------- |
| `path_or_stream`    | `str \| BinaryIO`                    | —                        | Filesystem path or an open binary file object              |
| `params`            | `AddParams \| None`                  | `None`                   | Chunking parameters (see [AddParams](#addparams))          |
| `timeout`           | `float \| None`                      | `config.default_timeout` | Timeout in seconds for the DHT provide step                |
| `progress_callback` | `Callable[[int, int], None] \| None` | `None`                   | Called with `(bytes_written, total_bytes)` during chunking |
| **Returns**         | `str`                                | —                        | Root CIDv1 string (base32)                                 |

```python
cid = await peer.add_file("/path/to/file.txt")

# With progress reporting
def on_progress(written, total):
    print(f"{written}/{total} bytes")

cid = await peer.add_file("/path/to/large.bin", progress_callback=on_progress)
```

> **Concurrency note:** `add_file()` holds the internal `RWLock` in read mode. Multiple
> concurrent `add_file()` calls are safe. GC (`peer.gc()`) will wait for all active
> `add_file()` calls to complete before running.

______________________________________________________________________

#### `await peer.get_file(cid_str, provider_addr=None, output_path=None, timeout=None, stream=False) → bytes | AsyncIterator[bytes] | None`

Fetches a file by CID, resolving DAG-PB / UnixFS nodes and reassembling chunks.

| Parameter       | Type                   | Default                  | Description                                                           |
| --------------- | ---------------------- | ------------------------ | --------------------------------------------------------------------- |
| `cid_str`       | `str`                  | —                        | The CID to fetch                                                      |
| `provider_addr` | `str \| None`          | `None`                   | Direct multiaddr of the provider peer. If set, bypasses DHT discovery |
| `output_path`   | `str \| None`          | `None`                   | Write content directly to this path. Returns `None`                   |
| `timeout`       | `float \| None`        | `config.default_timeout` | Per-block fetch timeout                                               |
| `stream`        | `bool`                 | `False`                  | If `True`, returns an `AsyncIterator[bytes]` instead of buffering     |
| **Returns**     | `bytes`                | —                        | Full file content (when `stream=False` and `output_path=None`)        |
| **Returns**     | `AsyncIterator[bytes]` | —                        | Chunk iterator (when `stream=True`)                                   |
| **Returns**     | `None`                 | —                        | When `output_path` is set                                             |
| **Raises**      | `BlockNotFoundError`   | —                        | If the block cannot be found locally or over the network              |

```python
# Default: returns bytes
data = await peer.get_file(cid)

# Streaming (for large files)
async for chunk in await peer.get_file(cid, stream=True):
    process(chunk)

# Write directly to disk
await peer.get_file(cid, output_path="/tmp/output.bin")

# Direct connect to a known peer (no DHT lookup)
data = await peer.get_file(cid, provider_addr="/ip4/192.168.1.10/tcp/4001/p2p/12D3Koo...")
```

______________________________________________________________________

### DAG / Node Operations

______________________________________________________________________

#### `await peer.add_node(node, codec="dag-json", timeout=None) → str`

Encodes `node` using the specified IPLD codec, computes a CIDv1, writes it to the local
blockstore, and announces it to the DHT / IPNI.

| Parameter   | Type                                  | Default                  | Description                                        |
| ----------- | ------------------------------------- | ------------------------ | -------------------------------------------------- |
| `node`      | `dict \| list \| str \| int \| bytes` | —                        | The data to store                                  |
| `codec`     | `str`                                 | `"dag-json"`             | IPLD codec: `"dag-json"`, `"dag-cbor"`, or `"raw"` |
| `timeout`   | `float \| None`                       | `config.default_timeout` | Timeout for the DHT provide step                   |
| **Returns** | `str`                                 | —                        | CIDv1 string (base32)                              |

```python
# DAG-JSON (human-readable, deterministic)
cid = await peer.add_node({"key": "value"}, codec="dag-json")

# DAG-CBOR (compact, deterministic — preferred for linked DAGs)
cid = await peer.add_node({"data": b"\x00\x01", "link": {"/": other_cid}}, codec="dag-cbor")

# Raw bytes
cid = await peer.add_node(b"raw binary data", codec="raw")
```

______________________________________________________________________

#### `await peer.get_node(cid_str, provider_addr=None, timeout=None) → dict | list | str | int | bytes`

Fetches and decodes a DAG node by CID. Checks the local blockstore first; falls back to
network fetch if not found locally.

| Parameter       | Type                  | Default                  | Description                                   |
| --------------- | --------------------- | ------------------------ | --------------------------------------------- |
| `cid_str`       | `str`                 | —                        | The CID to fetch                              |
| `provider_addr` | `str \| None`         | `None`                   | Direct multiaddr to bypass DHT discovery      |
| `timeout`       | `float \| None`       | `config.default_timeout` | Per-block fetch timeout                       |
| **Returns**     | `dict \| list \| ...` | —                        | Decoded Python object (type depends on codec) |
| **Raises**      | `BlockNotFoundError`  | —                        | If block not found                            |

```python
node = await peer.get_node(cid)
print(node["key"])  # "value"
```

______________________________________________________________________

#### `await peer.remove_node(cid_str) → None`

Deletes a block from the local blockstore. Does not check pins — use with care.

| Parameter | Type  | Description       |
| --------- | ----- | ----------------- |
| `cid_str` | `str` | The CID to remove |

______________________________________________________________________

#### `await peer.has_block(cid_str) → bool`

Returns `True` if the block is present in the local blockstore.

| Parameter | Type  | Description      |
| --------- | ----- | ---------------- |
| `cid_str` | `str` | The CID to check |

______________________________________________________________________

### Pinning

______________________________________________________________________

#### `await peer.add_pin(cid_str, recursive=True) → None`

Marks a CID as pinned, protecting it from garbage collection.

| Parameter   | Type   | Default | Description                                                                                    |
| ----------- | ------ | ------- | ---------------------------------------------------------------------------------------------- |
| `cid_str`   | `str`  | —       | The CID to pin                                                                                 |
| `recursive` | `bool` | `True`  | If `True`, pins the root and all reachable linked blocks. If `False`, pins only the root block |

```python
await peer.add_pin(cid, recursive=True)   # pin entire DAG
await peer.add_pin(cid, recursive=False)  # pin root block only
```

______________________________________________________________________

#### `await peer.remove_pin(cid_str) → None`

Removes a pin. The block becomes eligible for garbage collection on the next `gc()` call.

| Parameter  | Type               | Description                        |
| ---------- | ------------------ | ---------------------------------- |
| `cid_str`  | `str`              | The CID to unpin                   |
| **Raises** | `PinNotFoundError` | If the CID is not currently pinned |

______________________________________________________________________

#### `await peer.list_pins(type_filter="all") → dict[str, str]`

Returns a mapping of `{cid_str: pin_type}` for all currently pinned CIDs.

| Parameter     | Type             | Default | Description                                             |
| ------------- | ---------------- | ------- | ------------------------------------------------------- |
| `type_filter` | `str`            | `"all"` | One of `"all"`, `"direct"`, `"recursive"`, `"indirect"` |
| **Returns**   | `dict[str, str]` | —       | `{cid: pin_type}` mapping                               |

Pin types:

| Type          | Meaning                                                |
| ------------- | ------------------------------------------------------ |
| `"direct"`    | Root block explicitly pinned with `recursive=False`    |
| `"recursive"` | Root block explicitly pinned with `recursive=True`     |
| `"indirect"`  | Reachable from a recursive pin but not directly pinned |

______________________________________________________________________

### Garbage Collection

______________________________________________________________________

#### `await peer.gc() → GCResult`

Runs a mark-and-sweep garbage collection pass. All blocks not reachable from a pinned
root are deleted from the blockstore.

Takes an exclusive write lock — all concurrent `add_file()` / `add_node()` calls will
wait until GC completes.

| **Returns**         | Type  | Description                                     |
| ------------------- | ----- | ----------------------------------------------- |
| `.reclaimed_blocks` | `int` | Number of blocks deleted                        |
| `.retained_blocks`  | `int` | Number of blocks retained (reachable from pins) |

```python
result = await peer.gc()
print(f"GC reclaimed {result.reclaimed_blocks} blocks")
```

______________________________________________________________________

### IPNS

______________________________________________________________________

#### `await peer.publish_name(value, lifetime_hours=24) → str`

Creates a signed IPNS record mapping this peer's `PeerID` to `value` and publishes it
to the DHT.

| Parameter        | Type  | Default | Description                                        |
| ---------------- | ----- | ------- | -------------------------------------------------- |
| `value`          | `str` | —       | The value to publish (typically `/ipfs/{cid}`)     |
| `lifetime_hours` | `int` | `24`    | Record validity period in hours                    |
| **Returns**      | `str` | —       | This peer's base58 `PeerID` (the stable IPNS name) |

```python
name = await peer.publish_name(f"/ipfs/{cid}", lifetime_hours=48)
print(f"IPNS name: {name}")
```

______________________________________________________________________

#### `await peer.resolve_name(peer_id_str, timeout=None) → str`

Fetches the IPNS record for `peer_id_str` from the DHT and returns its value after full
cryptographic validation (signature + expiry check).

| Parameter     | Type            | Default                  | Description                                        |
| ------------- | --------------- | ------------------------ | -------------------------------------------------- |
| `peer_id_str` | `str`           | —                        | Base58 `PeerID` string to resolve                  |
| `timeout`     | `float \| None` | `config.default_timeout` | DHT lookup timeout                                 |
| **Returns**   | `str`           | —                        | The validated value from the record                |
| **Raises**    | `RoutingError`  | —                        | If not found, signature invalid, or record expired |

```python
value = await peer.resolve_name("12D3KooW...")
cid = value.replace("/ipfs/", "")
```

______________________________________________________________________

### CAR Files

______________________________________________________________________

#### `await peer.export_car(cid_str, output_path) → None`

Traverses the DAG rooted at `cid_str` and writes all blocks to `output_path` as a
CARv1 archive. I/O is fully async (`trio.open_file`).

| Parameter     | Type  | Description                  |
| ------------- | ----- | ---------------------------- |
| `cid_str`     | `str` | Root CID to export           |
| `output_path` | `str` | Destination `.car` file path |

```python
await peer.export_car(root_cid, "archive.car")
```

______________________________________________________________________

#### `await peer.import_car(input_path) → list[str]`

Reads a CARv1 file and writes all blocks into the local blockstore.

| Parameter    | Type        | Description                                 |
| ------------ | ----------- | ------------------------------------------- |
| `input_path` | `str`       | Source `.car` file path                     |
| **Returns**  | `list[str]` | Root CID strings declared in the CAR header |

```python
roots = await peer.import_car("archive.car")
node = await peer.get_node(roots[0])
```

______________________________________________________________________

### Subsystem Accessors

For compatibility with upstream `go-ipfs-lite` interfaces, these accessors expose internal subsystems. They are rarely needed for high-level operations.

| Method            | Returns             | Description                                                                                         |
| ----------------- | ------------------- | --------------------------------------------------------------------------------------------------- |
| `session()`       | `Peer`              | Returns `self`. (In Go this returns a `Session` struct; in Python the Peer acts as its own session) |
| `block_store()`   | `BlockStoreAdapter` | Returns the local blockstore (same as `peer.blockstore` attribute)                                  |
| `exchange()`      | `Bitswap`           | Returns the Bitswap exchange instance                                                               |
| `block_service()` | `MerkleDag`         | Returns the DAG service responsible for UnixFS/IPLD chunking and linking                            |

______________________________________________________________________

### Attributes

| Attribute         | Type                              | Description                                                                          |
| ----------------- | --------------------------------- | ------------------------------------------------------------------------------------ |
| `peer.host`       | `HostAdapter`                     | The libp2p host. Use `peer.host.id()` for PeerID, `peer.host.addrs()` for multiaddrs |
| `peer.routing`    | `TieredRouting \| RoutingAdapter` | The routing layer                                                                    |
| `peer.blockstore` | `BlockStoreAdapter`               | The local blockstore                                                                 |
| `peer.config`     | `Config`                          | The configuration this peer was created with                                         |

______________________________________________________________________

## `Config`

Node configuration dataclass. All fields have defaults.

**Import:**

```python
from py_ipfs_lite.config import Config
```

```python
@dataclass(slots=True)
class Config:
    offline: bool = False
    reprovide_interval_seconds: int = 43200
    reprovider_strategy: str = "all"
    conn_mgr_high_water: int = 900
    conn_mgr_low_water: int = 600
    blockstore_type: str = "filesystem"
    blockstore_path: str | None = ".py_ipfs_lite/blocks"
    use_ipni: bool = True
    ipni_endpoint: str = "https://cid.contact"
    default_timeout: float = 30.0
```

| Field                        | Type          | Default                  | Description                                                                                  |
| ---------------------------- | ------------- | ------------------------ | -------------------------------------------------------------------------------------------- |
| `offline`                    | `bool`        | `False`                  | Disable all network activity (DHT, Bitswap, IPNI). Useful for testing and CAR-only workflows |
| `reprovide_interval_seconds` | `int`         | `43200` (12h)            | How often the Reprovider re-announces all pinned blocks to the DHT. Set to `-1` to disable   |
| `reprovider_strategy`        | `str`         | `"all"`                  | Which blocks to announce. Only `"all"` is currently active                                   |
| `conn_mgr_high_water`        | `int`         | `900`                    | Maximum number of connections before pruning begins                                          |
| `conn_mgr_low_water`         | `int`         | `600`                    | Target connection count after pruning                                                        |
| `blockstore_type`            | `str`         | `"filesystem"`           | `"filesystem"` for disk persistence, `"memory"` for ephemeral in-process storage             |
| `blockstore_path`            | `str \| None` | `".py_ipfs_lite/blocks"` | Directory for the filesystem blockstore. Ignored when `blockstore_type="memory"`             |
| `use_ipni`                   | `bool`        | `True`                   | Enable IPNI (`cid.contact`) as a routing layer alongside KadDHT                              |
| `ipni_endpoint`              | `str`         | `"https://cid.contact"`  | IPNI HTTP endpoint (IPIP-337)                                                                |
| `default_timeout`            | `float`       | `30.0`                   | Default per-operation timeout in seconds                                                     |

______________________________________________________________________

## `AddParams`

Parameters controlling how `add_file()` chunks and hashes a file.

**Import:**

```python
from py_ipfs_lite.config import AddParams
```

```python
@dataclass(slots=True)
class AddParams:
    chunker: str = "size-262144"
    raw_leaves: bool = True
    hash_fun: str = "sha2-256"
```

| Field        | Type   | Default         | Description                                                                                              |
| ------------ | ------ | --------------- | -------------------------------------------------------------------------------------------------------- |
| `chunker`    | `str`  | `"size-262144"` | Chunking strategy. Format: `"size-{bytes}"`. Default produces 256 KiB chunks                             |
| `raw_leaves` | `bool` | `True`          | If `True`, leaf blocks are stored as raw bytes (not wrapped in UnixFS). Matches Kubo's default for CIDv1 |
| `hash_fun`   | `str`  | `"sha2-256"`    | Hash function for CID computation. `"sha2-256"` is the IPFS default                                      |

```python
params = AddParams(chunker="size-524288")  # 512 KiB chunks
cid = await peer.add_file("/path/to/large.bin", params=params)
```

______________________________________________________________________

## Exceptions

All exceptions inherit from `IPFSLiteError`.

**Import:**

```python
from py_ipfs_lite.exceptions import (
    IPFSLiteError,
    BlockNotFoundError,
    PinNotFoundError,
    PeerNotStartedError,
    RoutingError,
)
```

### Hierarchy

```
IPFSLiteError (base)
├── BlockNotFoundError    — block/CID not in local store or network
├── PinNotFoundError      — operation on a non-existent pin
├── PeerNotStartedError   — called a method before peer.start()
└── RoutingError          — DHT/IPNS publish, resolve, or validation failure
```

### When each is raised

| Exception             | Raised by                          | Condition                                                                     |
| --------------------- | ---------------------------------- | ----------------------------------------------------------------------------- |
| `BlockNotFoundError`  | `get_file()`, `get_node()`         | Block not found locally or via Bitswap after timeout                          |
| `PinNotFoundError`    | `remove_pin()`                     | CID is not in the pin store                                                   |
| `PeerNotStartedError` | Any `Peer` method                  | `peer.start()` has not been called                                            |
| `RoutingError`        | `resolve_name()`, `publish_name()` | DHT lookup failed, IPNS signature invalid, record expired, or pubkey mismatch |

```python
from py_ipfs_lite.exceptions import BlockNotFoundError, RoutingError

try:
    data = await peer.get_file(cid)
except BlockNotFoundError:
    print("Content not available")

try:
    value = await peer.resolve_name(peer_id)
except RoutingError as e:
    print(f"IPNS resolution failed: {e}")
```
