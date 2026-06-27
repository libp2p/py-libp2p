# DHT and Routing

This guide explains how `py-ipfs-lite` discovers content and peers, how the two routing
layers (KadDHT and IPNI) work together, and when to use direct connections instead of
relying on discovery.

**Relevant examples:**

- [`examples/02_dht_discovery.py`](../../examples/02_dht_discovery.py) — finding content
  by CID alone via DHT, with no `provider_addr` hint

**Run it:**

```bash
uv run python examples/02_dht_discovery.py
```

______________________________________________________________________

## Two Routing Layers

`py-ipfs-lite` uses a `TieredRouting` stack. When you call `get_file(cid)` or
`get_node(cid)` without a `provider_addr`, the routing layer is asked to find providers
for that CID. It queries both layers in order, deduplicates results, and returns up to
20 providers:

```
get_file(cid)  ─►  TieredRouting.find_providers(cid)
                        │
                        ├─ 1. KadDHT (py-libp2p)
                        │      walks the Kademlia routing table,
                        │      asks peers closest to hash(cid)
                        │
                        └─ 2. IPNI / cid.contact  (if use_ipni=True)
                               HTTP GET /routing/v1/providers/{cid}
                               falls back to /cid/{cid} native API
```

If either layer returns enough providers, the second layer is skipped. The first provider
that responds to a Bitswap WANT wins; the rest are abandoned.

### Layer 1 — KadDHT

The Kademlia Distributed Hash Table is the native IPFS content routing protocol. Every
peer that announces a CID writes a provider record in the DHT under the CID's multihash
key. A DHT `find_providers` query walks the routing table to peers closest to that key
and asks them for the record.

- **Strengths:** Fully decentralized, no single point of failure, works peer-to-peer
  without any HTTP infrastructure.
- **Practical latency:** 2–10 seconds for a cold lookup on the public network (DHT walks
  take multiple hops). Instant for peers already in the local routing table.
- **Requires bootstrap:** The peer must have connected to at least one bootstrap node
  (or another peer) before DHT lookups work. In `offline=True` mode, KadDHT is disabled.

### Layer 2 — IPNI / cid.contact

[IPNI (InterPlanetary Network Indexer)](https://cid.contact) is a delegated routing
service. It aggregates provider records submitted by major storage providers and public
IPFS nodes, and exposes them via a simple HTTP API (IPIP-337).

- **Strengths:** Millisecond lookups (single HTTP request vs multiple DHT hops), covers
  CIDs stored by large providers (web3.storage, Storacha, Filecoin SP nodes).
- **Limitations:** Only covers CIDs that have been explicitly submitted to IPNI.
  Ephemeral or private content will not appear here. `py-ipfs-lite` does not *submit*
  to IPNI (the `provide()` call on `DelegatedHTTPRouting` is intentionally a no-op —
  IPNI requires authentication to accept provider records).
- **Can be disabled:** `Config(use_ipni=False)` removes IPNI from the stack entirely,
  leaving only KadDHT.

```python
# Default: KadDHT + IPNI
peer = Peer(Config(), listen_addrs=["/ip4/0.0.0.0/tcp/4001"])

# KadDHT only — no outbound HTTP requests to cid.contact
peer = Peer(Config(use_ipni=False), listen_addrs=["/ip4/0.0.0.0/tcp/4001"])

# Custom IPNI endpoint (e.g. a private indexer)
peer = Peer(
    Config(ipni_endpoint="https://my-private-indexer.example.com"),
    listen_addrs=["/ip4/0.0.0.0/tcp/4001"]
)
```

______________________________________________________________________

## Example 02: DHT Discovery by CID Alone

[`examples/02_dht_discovery.py`](../../examples/02_dht_discovery.py)

This example is the clearest demonstration of the routing layer: Peer B fetches a file
from Peer A **without being told Peer A's address** — it discovers Peer A through the
DHT.

```python
import trio
from py_ipfs_lite.peer import Peer
from py_ipfs_lite.config import Config

async def main():
    # Start two independent peers
    peer_a = Peer(Config(reprovide_interval_seconds=-1), listen_addrs=["/ip4/127.0.0.1/tcp/0"])
    peer_b = Peer(Config(reprovide_interval_seconds=-1), listen_addrs=["/ip4/127.0.0.1/tcp/0"])

    await peer_a.start()
    await peer_b.start()

    # Connect B to A so they share a routing table
    # (In production you'd use public bootstrap peers instead)
    peer_a_addr = str(peer_a.host.addrs()[0])
    await peer_b.bootstrap([peer_a_addr])

    # Peer A stores a file — this adds the block and announces the CID to the DHT
    cid = await peer_a.add_file(__file__)
    print(f"Peer A added: {cid}")

    # Peer B fetches by CID — no provider_addr needed.
    # get_file() calls TieredRouting.find_providers(cid),
    # discovers Peer A's address from the DHT, connects, and pulls the block via Bitswap.
    content = await peer_b.get_file(cid)
    print(f"Peer B fetched {len(content)} bytes via DHT discovery")

    assert len(content) > 0
    await peer_b.close()
    await peer_a.close()

trio.run(main)
```

### The sequence inside `get_file(cid)`

```
peer_b.get_file(cid)
    │
    ├─ 1. Check local blockstore → not found
    │
    ├─ 2. TieredRouting.find_providers(cid)
    │       └─ KadDHT.find_providers → finds Peer A (it announced via add_file)
    │
    ├─ 3. Connect to Peer A via libp2p Noise/Yamux
    │
    ├─ 4. Bitswap WANT_HAVE + WANT_BLOCK exchange
    │       └─ Peer A sends the block bytes
    │
    └─ 5. Verify block hash == cid, decode, return bytes
```

______________________________________________________________________

## Bootstrap: Joining the DHT

The DHT routing table starts empty. To discover other peers, you must connect to at
least one known peer — a **bootstrap peer**. Once connected, the KadDHT implementation
gradually fills its routing table by learning about peers from its neighbors.

```python
from py_ipfs_lite.cli import DEFAULT_BOOTSTRAP_PEERS

peer = Peer(Config(), listen_addrs=["/ip4/0.0.0.0/tcp/4001"])
await peer.start()

# Connect to the public IPFS bootstrap nodes
await peer.bootstrap(DEFAULT_BOOTSTRAP_PEERS)
# After this call, DHT lookups for any public CID work
```

The default bootstrap peers are the official libp2p/IPFS infrastructure nodes:

```python
DEFAULT_BOOTSTRAP_PEERS = [
    "/dnsaddr/bootstrap.libp2p.io/p2p/QmNnooDu7bfjPFoTZYxMNLWUQJyrVwtbZg5gBMjTezGAJN",
    "/dnsaddr/bootstrap.libp2p.io/p2p/QmQCU2EcMqAqQPR2i9bChDtGNJchTbq5TbXJJ16u19uLTa",
    "/dnsaddr/bootstrap.libp2p.io/p2p/QmbLHAnMoJPWSCR5Zhtx6BHJX9KiKNN6tpvbUcqanj75Nb",
    "/ip4/104.131.131.82/tcp/4001/p2p/QmaCpDMGvV2BGHeYERUEnRQAwe3N8SzbUtfsmvsqQLuvuJ",
]
```

The `daemon` subcommand and `add`/`get` CLI commands call `bootstrap()` automatically.
When using the SDK directly, call it yourself after `peer.start()` if you need public
DHT access.

______________________________________________________________________

## Direct Connect: Bypassing Discovery

If you already know the provider's multiaddr (because you control both peers, or the
address is in a config file), pass `provider_addr` directly to skip the DHT/IPNI
lookup entirely:

```python
# No DHT lookup — connects directly
content = await peer.get_file(
    cid,
    provider_addr="/ip4/192.168.1.10/tcp/4001/p2p/12D3Koo..."
)
```

This is faster, more reliable in local network environments, and mandatory when running
in `offline=True` mode (where DHT is disabled).

Use direct connect for:

- Local tests between two in-process peers (see Examples 01, 11, 14)
- Cross-peer transfers in controlled environments (AI Agent agent clusters)
- `offline=True` workflows where no DHT is available

Use DHT discovery for:

- Fetching public IPFS content by CID (e.g., content added by Kubo or web3.storage)
- Multi-peer scenarios where provider addresses are not known in advance

______________________________________________________________________

## Reprovider: Keeping Your CIDs Discoverable

Adding a file announces its CID to the DHT once. DHT provider records have a TTL of
approximately 24 hours. To stay discoverable on the public network, the **Reprovider**
background task periodically re-announces all pinned CIDs.

```python
# Default: re-announce every 12 hours
peer = Peer(Config(reprovide_interval_seconds=43200), ...)

# More aggressive: every hour
peer = Peer(Config(reprovide_interval_seconds=3600), ...)

# Disable (useful for tests and offline workflows)
peer = Peer(Config(reprovide_interval_seconds=-1), ...)
```

The Reprovider only re-announces blocks that are **pinned**. Unpinned cached blocks are
not re-announced — only blocks that have been explicitly protected from GC.

______________________________________________________________________

## Routing in Offline Mode

Setting `Config(offline=True)` disables both KadDHT and IPNI entirely. In this mode:

- `add_file()` and `add_node()` write to the local blockstore only — no DHT announce.
- `get_file()` and `get_node()` succeed only if the block is already in the local
  blockstore, or if `provider_addr` is supplied (direct Bitswap connect still works).
- `bootstrap()` is a no-op.
- `publish_name()` and `resolve_name()` do not reach the DHT.

This mode is designed for CAR import/export workflows, offline processing pipelines, and
test environments where network access is undesirable.
