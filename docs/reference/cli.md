# CLI Reference

`py-ipfs-lite` ships a command-line interface with five subcommands. All subcommands
share a set of common flags.

**Invoke:**

```bash
uv run py-ipfs-lite <subcommand> [flags]
```

Or after `pip install`:

```bash
py-ipfs-lite <subcommand> [flags]
```

______________________________________________________________________

## Global flags

Available on every subcommand.

| Flag      | Type | Default | Description                                   |
| --------- | ---- | ------- | --------------------------------------------- |
| `--debug` | bool | `false` | Enable debug-level logging for all components |

______________________________________________________________________

## Common flags

Shared by all subcommands.

| Flag                | Type | Default                | Description                                                                                     |
| ------------------- | ---- | ---------------------- | ----------------------------------------------------------------------------------------------- |
| `--port`            | int  | `0` (random)           | P2P listening port. `0` picks a random free port                                                |
| `--seed`            | str  | `None`                 | Deterministic seed for the peer's Ed25519 identity key. Same seed → same PeerID across restarts |
| `--offline`         | bool | `false`                | Disable all network activity (DHT, Bitswap, IPNI)                                               |
| `--blockstore-type` | str  | `filesystem`           | `filesystem` (persistent) or `memory` (ephemeral)                                               |
| `--blockstore-path` | str  | `.py_ipfs_lite/blocks` | Directory for the filesystem blockstore                                                         |
| `--no-ipni`         | bool | `false`                | Disable IPNI (cid.contact) routing. Only KadDHT will be used                                    |
| `--ipni-endpoint`   | str  | `https://cid.contact`  | IPNI HTTP endpoint URL                                                                          |

______________________________________________________________________

## `daemon`

Starts a long-running peer node. Can optionally serve the HTTP API.

```bash
uv run py-ipfs-lite daemon [flags]
```

### Flags

All common flags, plus:

| Flag                   | Type | Default       | Description                                                    |
| ---------------------- | ---- | ------------- | -------------------------------------------------------------- |
| `--api`                | bool | `false`       | Enable the Kubo-compatible HTTP API server                     |
| `--api-host`           | str  | `127.0.0.1`   | Host address to bind the HTTP API to                           |
| `--api-port`           | int  | `5001`        | Port for the HTTP API server                                   |
| `--reprovide-interval` | int  | `43200` (12h) | Seconds between DHT re-announce cycles. Set to `-1` to disable |

### Examples

```bash
# P2P daemon only (no HTTP API)
uv run py-ipfs-lite daemon

# P2P daemon + HTTP API on default port
uv run py-ipfs-lite daemon --api

# HTTP API on a custom port, accessible from all interfaces
uv run py-ipfs-lite daemon --api --api-host 0.0.0.0 --api-port 8080

# Persistent identity (same PeerID across restarts)
uv run py-ipfs-lite daemon --api --seed "my-stable-node-seed"

# In-memory blockstore (no disk writes)
uv run py-ipfs-lite daemon --api --blockstore-type memory

# Offline mode (useful for CAR-only workflows)
uv run py-ipfs-lite daemon --offline --blockstore-type memory

# Disable IPNI, use DHT only
uv run py-ipfs-lite daemon --api --no-ipni
```

______________________________________________________________________

## `add`

Adds a file to the IPFS network. Starts an ephemeral peer, adds the file, announces the
CID to the DHT, and exits.

```bash
uv run py-ipfs-lite add <file> [flags]
```

### Arguments

| Argument | Required | Description             |
| -------- | -------- | ----------------------- |
| `file`   | ✅       | Path to the file to add |

### Flags

All common flags, plus:

| Flag                               | Type | Default       | Description                                                   |
| ---------------------------------- | ---- | ------------- | ------------------------------------------------------------- |
| `--chunker`                        | str  | `size-262144` | Chunking strategy. Format: `size-{bytes}`                     |
| `--hash-fun`                       | str  | `sha2-256`    | Hash function for CID computation                             |
| `--raw-leaves` / `--no-raw-leaves` | bool | `true`        | Store leaf blocks as raw bytes (matches Kubo's CIDv1 default) |

### Examples

```bash
# Add a file (prints CID)
uv run py-ipfs-lite add README.md

# Add with larger 1 MiB chunks
uv run py-ipfs-lite add large_dataset.bin --chunker size-1048576

# Add without announcing to the network
uv run py-ipfs-lite add secret.txt --offline

# Add to a specific local blockstore
uv run py-ipfs-lite add photo.jpg --blockstore-path /data/ipfs/blocks
```

______________________________________________________________________

## `get`

Fetches a file by CID. Starts an ephemeral peer, discovers the content, downloads it,
and exits.

```bash
uv run py-ipfs-lite get <cid> [flags]
```

### Arguments

| Argument | Required | Description                       |
| -------- | -------- | --------------------------------- |
| `cid`    | ✅       | CIDv1 string of the file to fetch |

### Flags

All common flags, plus:

| Flag         | Type | Default | Description                                                           |
| ------------ | ---- | ------- | --------------------------------------------------------------------- |
| `--provider` | str  | `None`  | Direct multiaddr of the provider peer. If set, bypasses DHT discovery |
| `--out`      | str  | `None`  | Write content to this file path. If not set, prints to stdout         |

### Examples

```bash
# Fetch from DHT, print to stdout
uv run py-ipfs-lite get bafkrei...

# Fetch and save to a file
uv run py-ipfs-lite get bafkrei... --out /tmp/downloaded.txt

# Fetch directly from a known peer (no DHT lookup)
uv run py-ipfs-lite get bafkrei... \
  --provider /ip4/192.168.1.10/tcp/4001/p2p/12D3Koo... \
  --out /tmp/output.bin
```

______________________________________________________________________

## `dag-export`

Exports an IPLD DAG rooted at a CID to a CARv1 file. Starts an ephemeral peer (with
DHT bootstrap unless `--offline`), fetches any missing blocks over the network, writes
the CAR file, and exits.

```bash
uv run py-ipfs-lite dag-export <cid> <out> [flags]
```

### Arguments

| Argument | Required | Description                   |
| -------- | -------- | ----------------------------- |
| `cid`    | ✅       | Root CID of the DAG to export |
| `out`    | ✅       | Output `.car` file path       |

### Flags

All common flags.

### Examples

```bash
# Export a locally stored DAG to a CAR file
uv run py-ipfs-lite dag-export bafyrei... archive.car

# Export in offline mode (only locally available blocks)
uv run py-ipfs-lite dag-export bafyrei... archive.car --offline

# Export from a persistent blockstore
uv run py-ipfs-lite dag-export bafyrei... trace.car \
  --blockstore-path /data/ipfs/blocks
```

______________________________________________________________________

## `dag-import`

Imports all blocks from a CARv1 file into the local blockstore. Does not bootstrap to
the DHT (import is always local-only).

```bash
uv run py-ipfs-lite dag-import <file> [flags]
```

### Arguments

| Argument | Required | Description                       |
| -------- | -------- | --------------------------------- |
| `file`   | ✅       | Path to the `.car` file to import |

### Flags

All common flags.

### Examples

```bash
# Import a CAR file into the default blockstore
uv run py-ipfs-lite dag-import archive.car

# Import into an in-memory blockstore (useful for one-off inspection)
uv run py-ipfs-lite dag-import archive.car --blockstore-type memory

# Import into a specific persistent blockstore path
uv run py-ipfs-lite dag-import trace.car \
  --blockstore-path /data/ipfs/blocks
```
