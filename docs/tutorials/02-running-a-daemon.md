# Tutorial 02: Running a Daemon

By the end of this tutorial you will have:

- Started `py-ipfs-lite` as a long-running daemon with the HTTP API enabled
- Added a file and fetched it back using `curl`
- Checked your node identity and connected peers
- Known where to go for the full API reference

**Time:** ~10 minutes
**Prerequisites:** Completed [Tutorial 01](./01-your-first-peer.md), `curl` installed

______________________________________________________________________

## Step 1 — Start the Daemon

Open a terminal and run:

```bash
uv run py-ipfs-lite daemon --api --api-port 5001
```

You should see:

```
Starting py-ipfs-lite daemon...
Daemon Peer ID: 12D3KooWHNte...
Listening on 2 address(es):
  /ip4/127.0.0.1/tcp/4001/p2p/12D3KooWHNte...
  /ip4/192.168.1.10/tcp/4001/p2p/12D3KooWHNte...
Starting py-ipfs-lite HTTP API daemon at http://127.0.0.1:5001
Daemon is running. Press Ctrl+C to stop...
```

Leave this terminal open. **Open a second terminal** for the `curl` commands below.

### What the flags mean

| Flag         | Value     | Effect                                                               |
| ------------ | --------- | -------------------------------------------------------------------- |
| `--api`      | (boolean) | Enable the HTTP API server                                           |
| `--api-port` | `5001`    | The port Kubo uses by default — existing tools and scripts just work |

The daemon also:

- Bootstraps to the public IPFS DHT automatically
- Starts a Reprovider that re-announces your pinned CIDs every 12 hours
- Uses a **filesystem blockstore** at `.py_ipfs_lite/blocks` by default (data survives restarts)

> **Tip:** Add `--seed my-node-name` to get a **stable PeerID** that persists across
> restarts. Without it, a new random identity is generated every time.

______________________________________________________________________

## Step 2 — Add a File via the API

In your second terminal, create a test file and add it:

```bash
echo "Hello from the py-ipfs-lite daemon!" > hello.txt
curl -X POST -F "file=@hello.txt" http://127.0.0.1:5001/api/v0/add
```

Response:

```json
{"Name":"hello.txt","Hash":"bafkrei...","Size":"37"}
```

The `Hash` field is the CID of your file. Save it — you will use it in the next step.

______________________________________________________________________

## Step 3 — Fetch the File Back

```bash
curl "http://127.0.0.1:5001/api/v0/cat?arg=bafkrei..."
```

Response:

```
Hello from the py-ipfs-lite daemon!
```

The content is streamed back directly. For binary files, pipe into a file:

```bash
curl "http://127.0.0.1:5001/api/v0/cat?arg=bafkrei..." --output fetched.bin
```

______________________________________________________________________

## Step 4 — Check Your Node Identity

```bash
curl http://127.0.0.1:5001/api/v0/id
```

Response:

```json
{
  "ID": "12D3KooWHNte...",
  "Addresses": [
    "/ip4/127.0.0.1/tcp/4001/p2p/12D3KooWHNte...",
    "/ip4/192.168.1.10/tcp/4001/p2p/12D3KooWHNte..."
  ]
}
```

`ID` is your PeerID — the stable identifier other peers use to find and dial you.
`Addresses` are the multiaddrs you are listening on. Share these with another peer to
let them connect to you directly without going through the DHT.

______________________________________________________________________

## Step 5 — Check Connected Peers

After a few seconds of bootstrapping, your daemon will have connected to other nodes
on the public IPFS network:

```bash
curl http://127.0.0.1:5001/api/v0/swarm/peers
```

Response:

```json
{
  "Peers": [
    {
      "Peer": "QmNnooDu7bfjPFoTZYxMNLWUQJyrVwtbZg5gBMjTezGAJN",
      "Addr": "/ip4/104.131.131.82/tcp/4001",
      "Direction": 0
    },
    ...
  ]
}
```

If `Peers` is empty, the daemon is still bootstrapping — wait a few seconds and retry.
Once you have at least one peer, your node is part of the DHT and CIDs you add will
be discoverable by other nodes on the network.

______________________________________________________________________

## Step 6 — Stop the Daemon

Back in the daemon terminal, press **Ctrl-C**:

```
^C
Shutting down...
```

All background tasks are cancelled cleanly and the libp2p host is closed. The blocks
you added are still on disk in `.py_ipfs_lite/blocks/` — they will be available
immediately the next time you start the daemon.

______________________________________________________________________

## Common Configurations

### In-memory (ephemeral — no disk writes)

```bash
uv run py-ipfs-lite daemon --api --blockstore-type memory
```

Useful for testing. All data is lost when the daemon stops.

### Custom port with stable identity

```bash
uv run py-ipfs-lite daemon \
  --api \
  --api-port 5001 \
  --port 4001 \
  --seed "my-stable-node"
```

### Avoid port conflict if Kubo is already running

Kubo uses port 5001 for its API by default. If both are running, use a different port:

```bash
uv run py-ipfs-lite daemon --api --api-port 8085
```

### No DHT (offline / local-only)

```bash
uv run py-ipfs-lite daemon --api --offline
```

The HTTP API still works in full — add, cat, dag/put, dag/get, pin, GC all work
locally. Only DHT discovery and Bitswap with remote peers are disabled.

______________________________________________________________________

## What's Next?

| I want to…                                   | Go to…                                                              |
| -------------------------------------------- | ------------------------------------------------------------------- |
| Learn every daemon flag and what it does     | [CLI Reference — daemon](../reference/cli.md#daemon)                |
| See the full list of all 17 API endpoints    | [HTTP API Reference](../reference/http-api.md)                      |
| Understand the Reprovider loop and pinning   | [HTTP API Daemon guide](../guides/http-api-daemon.md)               |
| Keep content available long-term on Filecoin | [CAR Files and Filecoin guide](../guides/car-files-and-filecoin.md) |
| Run the daemon in production under systemd   | [Production Deployment guide](../guides/production-deployment.md)   |
