# py-ipfs-lite Documentation

Welcome to the `py-ipfs-lite` documentation. Use the table below to find what you need.

______________________________________________________________________

## Where Do I Go For…?

- **I'm new here** → start with the [Tutorials](#tutorials)
- **I know what I want to do, I need the steps** → [Guides](#guides)
- **I need to look up a method signature, flag, or endpoint** → [Reference](#reference)
- **I want to understand how it works inside** → [Architecture](./architecture.md)

______________________________________________________________________

## Tutorials

Step-by-step, hand-held, linear. Assumes no prior knowledge of IPFS.

| Tutorial                                                    | Description                                                                                |
| ----------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| [01 — Your First Peer](./tutorials/01-your-first-peer.md)   | Install, start an in-memory peer, add a file, store an IPLD node, fetch it back            |
| [02 — Running a Daemon](./tutorials/02-running-a-daemon.md) | Start the HTTP API daemon, use `curl` to add/cat files, check identity and connected peers |

______________________________________________________________________

## Guides

Goal-oriented. Each guide explains one topic in depth and shows it in context with examples.

### Core Concepts

| Guide                                                      | Description                                                                                                    |
| ---------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| [Persistence and GC](./guides/persistence-and-gc.md)       | Filesystem vs memory blockstore, pin types (direct/recursive/indirect), garbage collection and the RWLock      |
| [DHT and Routing](./guides/dht-and-routing.md)             | How content discovery works: KadDHT vs IPNI, TieredRouting, bootstrap, direct connect, Reprovider              |
| [Streaming Large Files](./guides/streaming-large-files.md) | `bytes` vs `stream=True` vs `output_path`, progress callbacks, chunking internals                              |
| [HTTP API Daemon](./guides/http-api-daemon.md)             | Running the daemon, all daemon flags, curl walkthroughs for examples 06 and 07                                 |
| [Observability](./guides/observability.md)                 | All 7 Prometheus metrics, examples 16/17/21, process-global and gauge-restart caveats, PromQL queries          |
| [Production Deployment](./guides/production-deployment.md) | Connection manager tuning, bootstrap config, timeouts, known limitations, security model, pre-flight checklist |

### Protocol Integrations

| Guide                                                        | Description                                                                        |
| ------------------------------------------------------------ | ---------------------------------------------------------------------------------- |
| [IPNS](./guides/ipns.md)                                     | Mutable pointers, sequence numbers, trust model, forged-record rejection           |
| [CAR Files and Filecoin](./guides/car-files-and-filecoin.md) | CARv1 format, export/import API, Filecoin storage pipeline                         |
| [Interop with Kubo](./guides/interop-with-kubo.md)           | Bitswap compatibility, protocol layers, direct libp2p connections, full round-trip |

### AI and Agent Use Cases

| Guide                                              | Description                                                                     |
| -------------------------------------------------- | ------------------------------------------------------------------------------- |
| [AI Agents and RAG](./guides/ai-agents-and-rag.md) | Verifiable inference logs, hash-linked memory chains, distributed RAG pipelines |

______________________________________________________________________

## Reference

Lookup-oriented. Precise. No explanations — just what you need to call the API.

| Reference                                       | Description                                                                                                          |
| ----------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| [Python SDK](./reference/python-sdk.md)         | Every `Peer` method with signature and parameter table; `Config` and `AddParams` fields; exceptions hierarchy        |
| [HTTP API](./reference/http-api.md)             | All 17 `/api/v0/*` endpoints — method, params, `curl` example, response JSON                                         |
| [CLI](./reference/cli.md)                       | All 5 subcommands (`daemon`, `add`, `get`, `dag-export`, `dag-import`) — every flag, default, and example invocation |
| [Examples Index](./reference/examples-index.md) | All 21 examples in one table — what each shows and which guide covers it                                             |

______________________________________________________________________

## Architecture

| Page                              | Description                                                                                              |
| --------------------------------- | -------------------------------------------------------------------------------------------------------- |
| [Architecture](./architecture.md) | Component model, adapter pattern, data flows (add and fetch), RWLock concurrency model, IPNS trust model |
