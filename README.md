# py-ipfs-lite

`py-ipfs-lite` is a lightweight, embeddable Python implementation of an IPFS node. It is built on top of `py-libp2p` and is designed to be fully interoperable with the official `go-ipfs-lite` library. 

This project allows you to run a minimal IPFS peer that can add, fetch, and provide files and generic DAG nodes over the public IPFS network (via Kad DHT), all while maintaining a minimal footprint compared to the full Kubo daemon.

## Features

- **Files & Data:** Add and retrieve files using standard UnixFS chunking and protocol buffers.
- **DHT & Discovery:** Automatically bootstraps to the IPFS network and discovers content providers using the Kademlia DHT.
- **DAG Nodes:** Store and retrieve generic `dag-json` nodes.
- **Blockstore:** Configurable storage backend supporting both in-memory and persistent filesystem storage.
- **Pinning & GC:** Pin important CIDs to protect them, and run Garbage Collection to reclaim space from unpinned blocks.
- **Opt-in HTTP API:** Includes a built-in FastAPI server that exposes standard IPFS HTTP RPC endpoints (e.g., `/api/v0/add`).
- **100% Go Interoperability:** Rigorously tested against `go-ipfs-lite` for exact CID hashing parity, block-level compatibility, and bi-directional large file transfers.

## Installation

This project uses `uv` for dependency management. Ensure you have `uv` installed.

```bash
# Clone the repository and run commands via uv
cd py-ipfs-lite
uv sync
```

---

## Usage & CLI Commands

The CLI is structured into three main subcommands: `daemon`, `add`, and `get`. 

You can execute the CLI using `uv run py-ipfs-lite <command>` or `uv run python -m py_ipfs_lite <command>`.

### Global Options
- `--debug`: Enable debug-level logging across all commands.

---

### 1. `daemon`
Starts a long-running P2P provider node. It will bootstrap to the DHT, optionally start the HTTP API, and continuously reprovide stored CIDs to the network.

**Usage:**
```bash
uv run py-ipfs-lite daemon [OPTIONS]
```

**Options:**
- `--port INTEGER`: P2P listening port. Defaults to `0` (find an available free port).
- `--seed STRING`: An optional seed string to generate a deterministic Peer ID.
- `--offline`: Run the node offline without connecting to bootstrap peers or the DHT.
- `--reprovide-interval INTEGER`: Interval (in seconds) to re-announce stored/pinned CIDs to the DHT. Defaults to `43200` (12 hours). Set to `-1` to disable.
- `--blockstore-type STRING`: Choose `memory` or `filesystem`. Defaults to `filesystem`.
- `--blockstore-path STRING`: Path to the local blockstore directory. Defaults to `.ipfs-lite-blockstore` in the current working directory.
- `--api`: **Opt-in flag** to launch the HTTP API server alongside the P2P daemon.
- `--api-host STRING`: Host address for the HTTP API (default: `127.0.0.1`).
- `--api-port INTEGER`: Port for the HTTP API (default: `5001`).

**Example:**
```bash
uv run py-ipfs-lite daemon --api --blockstore-type filesystem --blockstore-path ./my-store
```

---

### 2. `add`
Adds a file to the local blockstore, chunks it into UnixFS nodes, calculates the CID, and optionally announces it to the DHT.

**Usage:**
```bash
uv run py-ipfs-lite add <file> [OPTIONS]
```

**Arguments:**
- `file`: (Required) The path to the file you want to add.

**Options:**
- `--chunker STRING`: The chunking algorithm to use. Defaults to `size-262144` (256 KB chunks).
- `--hash-fun STRING`: The multihash algorithm to use for block CIDs. Defaults to `sha2-256`.
- `--raw-leaves` / `--no-raw-leaves`: Whether to use raw binary leaves or wrap leaf chunks in UnixFS protobufs. Defaults to `--raw-leaves`.
- `--port`, `--seed`, `--offline`, `--blockstore-type`, `--blockstore-path`: Same behavior as the `daemon` command.

**Example:**
```bash
uv run py-ipfs-lite add my_video.mp4 --chunker size-1048576
```

---

### 3. `get`
Fetches a file from the IPFS network by its CID. It resolves the CID to providers via the DHT, connects to them, and reconstructs the file.

**Usage:**
```bash
uv run py-ipfs-lite get <cid> [OPTIONS]
```

**Arguments:**
- `cid`: (Required) The base58 or base32 encoded CID of the content to fetch.

**Options:**
- `--out STRING`: Optional output file path. If not provided, the content is printed to standard output (stdout).
- `--provider STRING`: Explicit multiaddress of a provider to connect to directly, skipping DHT discovery.
- `--port`, `--seed`, `--offline`, `--blockstore-type`, `--blockstore-path`: Same behavior as the `daemon` command.

**Example:**
```bash
uv run py-ipfs-lite get bafybeigjwd... --out downloaded_video.mp4
```

---

## HTTP API Daemon

When the daemon is started with the `--api` flag, a `FastAPI` server is launched to handle incoming HTTP RPC requests. This allows external apps or frontends to use your node without writing Python code.

The following standard IPFS endpoints are available (usually on `http://127.0.0.1:5001`):

- **`POST /api/v0/add`**: Add a file (multipart/form-data). Returns CID info.
- **`POST /api/v0/cat?arg=<cid>`**: Stream back file content for a given CID.
- **`POST /api/v0/dag/put`**: Store a generic JSON node.
- **`POST /api/v0/dag/get?arg=<cid>`**: Retrieve a DAG node as JSON.
- **`POST /api/v0/pin/add?arg=<cid>`**: Pin a CID to prevent deletion.
- **`POST /api/v0/pin/rm?arg=<cid>`**: Unpin a CID.
- **`POST /api/v0/repo/gc`**: Run Garbage Collection on unpinned blocks.
- **`POST /api/v0/block/stat?arg=<cid>`**: Check local blockstore for a block and get its size.
- **`POST /api/v0/block/rm?arg=<cid>`**: Remove a block by CID.

**Test via cURL:**
```bash
curl -X POST -H "Content-Type: application/json" -d '{"message": "hello"}' "http://127.0.0.1:5001/api/v0/dag/put"
```

---

## Interoperability Testing

The `py-ipfs-lite` node includes a comprehensive interoperability test suite that spins up both `py-ipfs-lite` and a compiled `go-ipfs-lite` node to transfer files, cross-verify CIDs, and test lifecycle operations.

To run the interop tests:
```bash
cd interop
./run_interop.sh
```

**Interop coverage includes:**
1. Large file bi-directional chunk transfers (`py->go` and `go->py`).
2. Exact UnixFS CID hashing parity.
3. DAG node lifecycle execution (`add` -> `has` -> `remove`).
4. Proper unpinned garbage collection reclamation.
5. Generic DAG-JSON node storage and retrieval.
