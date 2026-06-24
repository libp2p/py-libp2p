# Examples Index

All 21 examples in the `examples/` directory, with a one-line description and a link to
the guide that walks through it in depth. Run any example with:

```bash
uv run python examples/<script>.py
```

---

| # | File | What it shows | Guide |
|---|---|---|---|
| 01 | [`01_embeddable_peers.py`](../../examples/01_embeddable_peers.py) | Bitswap file transfer between two in-process Python peers | [Tutorial: Your First Peer](../tutorials/01-your-first-peer.md) |
| 02 | [`02_dht_discovery.py`](../../examples/02_dht_discovery.py) | Finding content by CID alone via the Kademlia DHT | [DHT and Routing](../guides/dht-and-routing.md) |
| 03 | [`03_ipld_node.py`](../../examples/03_ipld_node.py) | Storing and retrieving generic IPLD DAG-JSON / DAG-CBOR nodes | [Tutorial: Your First Peer](../tutorials/01-your-first-peer.md) |
| 04 | [`04_pin_and_gc.py`](../../examples/04_pin_and_gc.py) | Direct vs recursive pinning; running GC and observing what is reclaimed | [Persistence and GC](../guides/persistence-and-gc.md) |
| 05a | [`05a_localstore_write.py`](../../examples/05a_localstore_write.py) | Writing blocks to a persistent filesystem blockstore | [Persistence and GC](../guides/persistence-and-gc.md) |
| 05b | [`05b_localstore_read.py`](../../examples/05b_localstore_read.py) | Reading blocks back from a persistent filesystem blockstore | [Persistence and GC](../guides/persistence-and-gc.md) |
| 06 | [`06_http_api.sh`](../../examples/06_http_api.sh) | Using the HTTP API via `curl` — add, cat, dag/get, pin | [HTTP API Daemon](../guides/http-api-daemon.md) |
| 07 | [`07_reprovider.sh`](../../examples/07_reprovider.sh) | Watching the Reprovider loop re-announce CIDs to the DHT | [HTTP API Daemon](../guides/http-api-daemon.md) |
| 08 | [`08_verifiable_inference.py`](../../examples/08_verifiable_inference.py) | Storing an AI inference log as a DAG-CBOR node; verifying it by CID | [AI Agents and RAG](../guides/ai-agents-and-rag.md) |
| 09 | [`09_kubo_interop.py`](../../examples/09_kubo_interop.py) | Two-way Bitswap exchange with a local Kubo daemon via the `ipfs` CLI | [Interop with Kubo](../guides/interop-with-kubo.md) |
| 10 | [`10_ipld_linked_dag.py`](../../examples/10_ipld_linked_dag.py) | Building and traversing a linked IPLD knowledge graph locally | [DHT and Routing](../guides/dht-and-routing.md) |
| 11 | [`11_car_export_import.py`](../../examples/11_car_export_import.py) | Exporting a DAG to a `.car` file; importing it on a fresh offline peer | [CAR Files and Filecoin](../guides/car-files-and-filecoin.md) |
| 12 | [`12_streaming_large_file.py`](../../examples/12_streaming_large_file.py) | Fetching a large chunked file with `stream=True`; progress callbacks | [Streaming Large Files](../guides/streaming-large-files.md) |
| 13 | [`13_agent_memory_chain.py`](../../examples/13_agent_memory_chain.py) | Hash-linked conversation memory chain — each turn links to the prior CID | [AI Agents and RAG](../guides/ai-agents-and-rag.md) |
| 14 | [`14_distributed_rag.py`](../../examples/14_distributed_rag.py) | Two-peer RAG pipeline — Indexer stores chunks, Retriever fetches by CID | [AI Agents and RAG](../guides/ai-agents-and-rag.md) |
| 15 | [`15_ipns_mutable_registry.py`](../../examples/15_ipns_mutable_registry.py) | Publish a versioned registry to IPNS; update the pointer; resolve it | [IPNS](../guides/ipns.md) |
| 16 | [`16_metrics_dashboard.py`](../../examples/16_metrics_dashboard.py) | Scraping Prometheus metrics from `/debug/metrics/prometheus` | [Observability](../guides/observability.md) |
| 17 | [`17_concurrent_ingestion_benchmark.py`](../../examples/17_concurrent_ingestion_benchmark.py) | Concurrent `add_file()` calls under the RWLock — safety and throughput | [Observability](../guides/observability.md) |
| 18 | [`18_ipns_trust_boundary.py`](../../examples/18_ipns_trust_boundary.py) | Adversarial demo: two forged-record strategies both correctly rejected | [IPNS — Trust Model](../guides/ipns.md#example-18-trust-model--the-flagship-security-demo) |
| 19 | [`19_filecoin_pipeline.py`](../../examples/19_filecoin_pipeline.py) | AI Agent inference trace → linked IPLD DAG → CARv1 → Filecoin | [CAR Files and Filecoin](../guides/car-files-and-filecoin.md) |
| 20 | [`20_kubo_round_trip.py`](../../examples/20_kubo_round_trip.py) | Full round-trip: Python writes DAG-JSON, Kubo reads; Kubo writes UnixFS, Python reads | [Interop with Kubo](../guides/interop-with-kubo.md) |
| 21 | [`21_resource_footprint.py`](../../examples/21_resource_footprint.py) | Measuring memory and CPU footprint of a running peer at rest and under load | [Observability](../guides/observability.md) |

---

> **Note on shell examples (06, 07):** These are bash scripts. Run them with:
> ```bash
> bash examples/06_http_api.sh
> bash examples/07_reprovider.sh
> ```
> Both require the daemon to be running first (`uv run py-ipfs-lite daemon --api`).
