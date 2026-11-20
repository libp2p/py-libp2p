# Metrics Integration Plan — INotifee-Style Event Bus for py-libp2p

**Scope:** Integrate observability (metrics) into **all peer discovery modules, Kad-DHT, Bitswap, pubsub, swarm, ping** using an event-driven architecture modeled on the existing **INotifee** pattern (`register_notifee` / `remove_notifee` / `_notify` fan-out in `libp2p/network/swarm.py`), so that whenever anything happens in a module, **everyone who wants to listen is notified** — the Prometheus exporter being one listener, with room for loggers, dashboards, tracing, and user code.

**Status:** Plan (pre-implementation). Every claim below was verified against the current codebase on branch `fix/dht-provide-improvements`.

---

## 1. Executive Summary

py-libp2p already has a *partial*, *single-consumer* metrics pipeline:

```
new_host(enable_metrics=True)
  └─ trio.open_memory_channel(100)          (libp2p/__init__.py:750-752)
       ├─ send end → Swarm → SwarmConnection → each NetStream.metric_send_channel
       └─ recv end → BasicHost.metric_recv_channel → get_metrics_recv_channel()
                                                          (abc.py:2208)
Emitters (today):
  - Swarm    → SwarmEvent      (dial/conn attempts+errors)      swarm.py:689,888,1722,1775,1800,1821
  - KadDHT   → KadDhtEvent     (inbound requests only)          kad_dht.py:1208
  - Pubsub   → GossipsubEvent  (inbound messages only)          pubsub.py:571
  - Ping     → PingEvent       (rtts / failures)                host/ping.py:251
Consumer (today):
  - Metrics.start_prometheus_server(recv_channel)                libp2p/metrics/metrics.py:45
      └─ match event: → KadDhtMetrics / GossipsubMetrics / SwarmMetrics / PingMetrics
```

**Gaps (verified):**
1. **Bitswap has zero events.** Nothing observable for wantlists, block transfer, sessions, provider queries, message queue batching.
2. **Peer discovery has zero metric events.** mDNS and Bootstrap only feed the app-facing `peerDiscovery` singleton (`discovery/events/peerDiscovery.py`); Random Walk, rendezvous have nothing.
3. **Kad-DHT is inbound-only.** `provide()`, `find_providers()`, `put_value()`, `get_value()`, `find_peer()`, lookups, republish, rate-limit hits, stream resets are invisible.
4. **Pubsub is inbound-only** — outbound publishes, subscriptions, validation results, mesh size invisible.
5. **Single consumer.** One `Metrics` aggregator; no way for additional listeners (logging, tracing, custom exporters) to attach.
6. **Blocking hot path.** `await stream.metric_send_channel.send(event)` in kad_dht.py:1208 and pubsub.py:571 blocks the protocol handler when the 100-deep channel is full.
7. **Hardcoded dispatch.** Adding a module means editing `metrics.py`'s `match` statement.
8. **High-cardinality labels.** Every counter uses `labelnames=["peer_id"]` — cardinality grows with every peer ever seen (a staging node with 2k+ peers in the peerstore creates 2k label sets per counter). go-libp2p deliberately avoids per-peer labels.

**The fix:** a per-host **`EventBus`** modeled on INotifee (and on go-libp2p's `event.Bus`):
- modules call `emit(event)` on "anything happens";
- any number of listeners `register_listener()` / `remove_listener()`;
- each listener gets a bounded queue drained by its own task — **emission never blocks the protocol hot path**, and a failing/slow listener never affects the emitter or other listeners (exactly the isolation `Swarm._notify` provides today, swarm.py:2707);
- the existing `Metrics` aggregator becomes one such listener (a `MetricsListener`);
- the old channel API stays working via a bridge listener (backward compat), then is deprecated.

---

## 2. Current State Analysis (verified)

### 2.1 The channel plumbing

| Step | Location |
|---|---|
| `new_host(enable_metrics=True)` opens `trio.open_memory_channel(100)` | `libp2p/__init__.py:750-752` |
| send end → `new_swarm(metric_send_channel=...)` | `__init__.py:788` |
| recv end → `BasicHost(metric_recv_channel=...)` | `__init__.py:815` |
| `Swarm.metric_send_channel` stored | `swarm.py:274` |
| propagated to connections | `swarm_connection.py:45, 292` |
| `NetStream.metric_send_channel` (per-stream) | `net_stream.py:126, 150`; `abc.py:341` |
| consumer accessor `IHost.get_metrics_recv_channel()` | `abc.py:2208`; `basic_host.py:627` |

### 2.2 Existing events & metrics

| Module | Event class | Fields | Metrics (prometheus_client) |
|---|---|---|---|
| Swarm | `SwarmEvent` (`metrics/swarm.py`) | conn_incoming, conn_incoming_error, dial_attempt, dial_attempt_error, peer_id | `swarm_incoming_conn{peer_id}`, `swarm_incoming_conn_error`, `swarm_dial_attempt`, `swarm_dial_attempt_error` |
| Kad-DHT | `KadDhtEvent` (`kad_dht.py:151`) | inbound, find_node, get_value, put_value, get_providers, add_provider, peer_id | `kad_inbound_total`, `kad_inbound_find_node/get_value/put_value/get_providers/add_provider{peer_id}` |
| Pubsub | `GossipsubEvent` (`pubsub.py:311`) | publish, subopts, control, message_size, peer_id | `gossipsub_received_total`, `gossipsub_publish_total`, `gossipsub_subopts_total`, `gossipsub_control_total{peer_id}`, `gossipsub_message_bytes` |
| Ping | `PingEvent` (`host/ping.py:37`) | peer_id, rtts[], failure_error | `ping` histogram (ms), `ping_failure{reason}` |

### 2.3 INotifee — the pattern to copy

`libp2p/network/swarm.py`:
- `register_notifee(notifee)` — append to `self.notifees` (line 2693)
- `remove_notifee(notifee)` — remove (line 2700)
- `_notify(method, *args)` — **fan-out**: each notifee runs in its own task inside a nursery, exceptions logged and isolated, concurrent (line 2707)
- wired events: `notify_connected`, `notify_disconnected`, `notify_opened_stream`, `notify_listen`, etc.
- real consumers: `TagStoreNotifee` (tag_store.py:509), `_IdentifyNotifee` (basic_host.py:141), `PubsubNotifee` (pubsub_notifee.py:21), `BitswapClient` itself (client.py:55)

Also relevant: the module-level **`peerDiscovery` singleton** (`discovery/events/peerDiscovery.py`) already implements register/unregister/emit for "peer discovered" — proof the pattern is idiomatic here, but it is *global*, per-process, and only carries `PeerInfo`.

### 2.4 What is missing, module by module

| Module | Instrumented today | Missing |
|---|---|---|
| **Bitswap** | nothing | want add/cancel, block received/sent (+size, +latency from want), messages sent/received by kind, queue depth/batch stats, session lifecycle, provider-query outcomes, errors |
| **Discovery — mDNS** | app callback only (`peerDiscovery`) | peer discovered/lost, service response counts, resolution failures |
| **Discovery — Bootstrap** | app callback only | peer discovered (source label), connect attempts (success/fail, duration), consecutive-failure removals |
| **Discovery — Random Walk** | nothing | walk start/finish, peers found per walk, duration, failures |
| **Discovery — Rendezvous** | nothing | register/discover attempts, outcomes |
| **Kad-DHT outbound** | nothing | lookups (target, duration, peers queried/found, success), provide, find_providers, put/get_value outbound, find_peer, routing-table refresh, republish (values + provider records), rate-limit hits, stream resets |
| **Pubsub outbound** | nothing | publish attempts (peers sent), subscribe/unsubscribe, validation results (accept/ignore/reject), mesh size per topic |
| **Swarm** | attempts/errors only | open-connection gauge, stream open/close, listener add/remove, periodic snapshot gauges |
| **rcmgr** | own parallel system (`rcmgr/metrics.py`, `prometheus_exporter.py`) | bridge decision (see §4.7) |

---

## 3. Target Architecture — `EventBus` (INotifee-style)

### 3.1 Concept

Mirror the INotifee contract 1:1, generalized from "network lifecycle callbacks" to "anything that happens anywhere":

| INotifee (today) | EventBus (new) |
|---|---|
| `network.register_notifee(notifee)` | `event_bus.register_listener(listener)` |
| `network.remove_notifee(notifee)` | `event_bus.remove_listener(listener)` |
| `Swarm._notify("connected", conn)` — fan-out to all notifees, isolated tasks | `await event_bus.emit(event)` — fan-out to all listeners |
| fixed callback surface (opened_stream, closed_stream, connected, …) | any typed event object; listeners filter by type |
| per-node (lives on Swarm) | per-node (lives on Host), see §3.5 |

Precedent: **go-libp2p `core/event` Bus** — `Emit(ctx, evt)` does a non-blocking send to every subscriber's channel; slow subscribers drop events rather than stall the emitter. py-libp2p already mirrors go-libp2p elsewhere, so this keeps the codebase idiom consistent.

### 3.2 New package: `libp2p/events/`

```
libp2p/events/
├── __init__.py          # re-exports: EventBus, IEventListener
├── bus.py               # EventBus + IEventListener (the core)
└── (event classes stay in their home modules — see §3.6)
```

### 3.3 API (proposed)

```python
# libp2p/events/bus.py

class IEventListener(ABC):
    """A listener that wants to be notified of module events.

    Mirrors INotifee's role: an object registered with the bus that
    receives events. Unlike INotifee there is no fixed callback surface —
    the listener receives typed event objects and filters by type.
    """
    @abstractmethod
    async def handle_event(self, event: Any) -> None: ...


class EventBus:
    def __init__(self, default_buffer_size: int = 256) -> None: ...

    def register_listener(
        self, listener: IEventListener, buffer_size: int | None = None
    ) -> None:
        """Subscribe. buffer_size = per-listener queue depth (drop-on-full)."""

    def remove_listener(self, listener: IEventListener) -> None: ...

    async def emit(self, event: Any) -> None:
        """Best-effort fan-out.

        - For each listener, `send_nowait` into its bounded queue.
        - If a queue is full → DROP the event, increment
          `bus_events_dropped_total{listener,event_type}` (observable).
        - Never blocks the caller; never raises into the emitter.
        """

    async def start(self, nursery: trio.Nursery) -> None:
        """Start one consumer task per listener:
           while True: event = await queue.receive()
                        try: await listener.handle_event(event)
                        except Exception: log (isolation, like Swarm._notify)
        """

    async def stop(self) -> None: ...
```

Design decisions, with rationale:

1. **Async `emit`** — matches the existing call sites (`await stream.metric_send_channel.send(event)`), and lets `emit` be a `send_nowait` loop internally so it is *non-blocking in practice*. Callers keep a one-line `await bus.emit(event)`.
2. **Queue-per-listener + consumer task** — this is what gives "notify everyone" without coupling: a listener that does I/O (HTTP push, file logging) cannot stall kad-dht's message loop. It also gives natural backpressure *isolation*: full queue → drop for *that* listener only.
3. **Drop-on-full (default) with a drop counter** — metrics are loss-tolerant; blocking is not. Operators see drops via the counter. A listener that needs reliability can register with a larger buffer.
4. **Exception isolation** — consumer tasks wrap `handle_event` in try/except and log, exactly like `Swarm._notify` (swarm.py:2707-2726). A buggy listener can never take down a module.
5. **Optional `sync=True` fast path** — a listener may opt into inline synchronous delivery (no queue) for sub-microsecond handlers (e.g. pure prometheus counter increments). Default is queued; keep this as a later optimization only if profiling shows queue overhead on the hot path.
6. **No event-type filtering in the bus core** — listeners see everything and filter cheaply (`isinstance`); if profiling later shows fan-out cost, add `subscribe(event_types=[...])` as an optimization (go-libp2p's `Subscribe(topic)`). Keep the core minimal now.

### 3.4 Where the bus lives — per-host, always on

- The bus is created in `new_host()` **unconditionally** (it is near-free with zero listeners — `emit` loops over an empty list). The `enable_metrics` flag stops gating plumbing; it now only controls the *compat bridge* (§3.6) and, later, auto-attaching the built-in `MetricsListener`.
- Accessor: `IHost.get_event_bus() -> EventBus` (new abstract on `abc.py`, implemented in `BasicHost`).
- Every module that needs to emit already holds a host reference:
  - Kad-DHT: `self.host` (kad_dht.py, provider_store.py, value_store.py, peer_routing.py)
  - Bitswap: `self.host` (client.py:101)
  - Pubsub: `self.host` (pubsub.py)
  - mDNS: constructed with `host=` (`create_mdns_discovery(network, host=host)`, basic_host.py)
  - Random Walk: `self.host` (random_walk.py:56)
  - Bootstrap: constructed in `BasicHost.__init__` — pass `event_bus=` into `BootstrapDiscovery` (bootstrap.py currently receives only `network`)
- Host lifecycle: `BasicHost.run()` calls `event_bus.start(nursery)`; shutdown calls `stop()`. (For DHT/pubsub/bitswap, which are separate `Service`s run by the app, emitting before/after host.run must be safe — `emit` with zero listeners is a no-op, and consumer tasks only matter once listeners exist.)

### 3.5 Backward compatibility — the bridge

The old channel API (`get_metrics_recv_channel()`, `Metrics.start_prometheus_server(recv_channel)`, `stream.metric_send_channel`) must keep working while modules migrate.

**Strategy: one emit path, two consumer paths.**

1. Modules migrate to `await host.get_event_bus().emit(event)` as the *only* emit path.
2. When `enable_metrics=True`, `new_host` registers a **`ChannelBridgeListener`** on the bus that forwards every event into the existing `metric_recv_channel` (replacing today's send-end→stream plumbing).
3. `Metrics.start_prometheus_server(recv_channel)` and `stream.metric_send_channel` remain untouched during the transition; examples/tests keep working.
4. After all modules + `MetricsListener` land, deprecate: remove `metric_send_channel` from `INetStream`, drop the bridge, and switch `Metrics` to listener mode. `get_metrics_recv_channel()` can remain as a deprecated shim returning `bus.to_recv_channel()` (a lazily-created channel fed by a bridge).

This keeps the PR reviewable: Phase 1-2 are pure plumbing with zero behavior change.

### 3.6 Where event classes live

Keep the existing convention (events live in their home modules, e.g. `KadDhtEvent` in `kad_dht.py`):
- `KadDhtEvent` — extend in place (`kad_dht.py:151`)
- `GossipsubEvent` — extend in place (`pubsub.py:311`)
- `PingEvent` — unchanged (`host/ping.py:37`)
- `SwarmEvent` — **move** out of `metrics/swarm.py` into `libp2p/network/events.py` (it is a network-layer event, not a metrics-layer class; re-export from `metrics/swarm.py` for compat)
- New: `BitswapEvent` → `libp2p/bitswap/events.py`
- New: `DiscoveryEvent` → `libp2p/discovery/events/events.py` (alongside the existing `peerDiscovery.py` singleton)
- New: `BusEvent`/drop counters live in `libp2p/events/bus.py`

---

## 4. Module-by-Module Instrumentation Plan

> Naming convention: follow the existing Rust-libp2p-style counters (`kad_inbound_total`, `swarm_dial_attempt`) and go-libp2p names where they exist (bitswap). Histograms for durations/sizes; gauges for current state (routing table size, wantlist size, mesh size) updated on change + periodic snapshot.

### 4.1 Kad-DHT (`libp2p/kad_dht/`)

**Extend `KadDhtEvent`** with outbound + operational fields (keep existing inbound fields).

| Event (field flags) | Emit site | Prometheus metric (new unless noted) |
|---|---|---|
| `inbound, find_node/get_value/put_value/get_providers/add_provider` (existing) | stream handler loop `kad_dht.py:1208` | existing counters (keep) |
| `lookup: target, duration_ms, peers_queried, peers_found, success` | `PeerRouting.find_closest_peers_network` (peer_routing.py:173) | `kad_lookup_total{result}`, `kad_lookup_duration_ms` (hist), `kad_lookup_peers_queried` (hist), `kad_lookup_peers_found` (hist) |
| `provide: key, peers_announced, duration_ms, success` | `provider_store.provide` (provider_store.py:207) + `kad_dht.provide` (kad_dht.py:1660) | `kad_provide_total{result}`, `kad_provide_duration_ms`, `kad_provide_peers_announced` |
| `find_providers: key, providers_found, duration_ms, success` | `provider_store.find_providers` (provider_store.py:343) | `kad_find_providers_total{result}`, `kad_find_providers_found` (hist) |
| `put_value_out: key, peers_stored, success` | `kad_dht.put_value` (kad_dht.py:1291) | `kad_put_value_total{result}` |
| `get_value_out: key, found, success` | `kad_dht.get_value` (kad_dht.py:1367) | `kad_get_value_total{result}` |
| `find_peer: peer_id, found, duration_ms` | `PeerRouting.find_peer` (peer_routing.py:71) | `kad_find_peer_total{result}` |
| `refresh: reason, peers_found` | `refresh_routing_table` (kad_dht.py:1272, peer_routing.py:477) | `kad_refresh_total{reason}` |
| `republish: record_type (value\|provider), count, errors` | `value_store._republish_records` (value_store.py:213), `provider_store._republish_provider_records` (provider_store.py:189) | `kad_republish_total{type,result}` |
| `rate_limited: peer_id` | `_check_provider_rate_limit` rejection (kad_dht.py:773) | `kad_rate_limited_total` |
| `stream_reset: peer_id, reason` | `should_reset` paths in handler loop | `kad_stream_reset_total{reason}` |
| `routing_table: total_peers, buckets` (snapshot) | periodic task (reuse the existing republish loop, kad_dht.py:404) | `kad_routing_table_peers` (gauge), `kad_routing_table_buckets` (gauge) |
| `value_store_size`, `provider_store_size` (snapshot) | same periodic loop | `kad_value_store_size` (gauge), `kad_provider_store_size` (gauge) |

Notes: the handler loop currently sends one `event` after each message (kad_dht.py:1206-1208) — keep that, just add fields. Outbound ops emit at the end of each operation with `duration_ms` measured via `trio.current_time()` deltas. Rate-limit and reset events should be emitted **inside** the handler where the decision is made (currently `logger.warning` sites).

### 4.2 Bitswap (`libp2p/bitswap/`) — from zero

New `libp2p/bitswap/events.py` with `BitswapEvent` (field flags) + emit points:

| Event | Emit site | Prometheus metric |
|---|---|---|
| `want_add: cid, want_type, priority` | `BitswapClient.add_wantlist`/`_send_wantlist_to_peer` (client.py:349-394) | `bitswap_wantlist_adds_total` |
| `want_cancel: cid` | cancel paths (client.py) | `bitswap_wantlist_cancels_total` |
| `wantlist_size: n` (snapshot) | on change + periodic | `bitswap_wantlist_entries` (gauge) |
| `block_received: cid, peer_id, size_bytes, latency_from_want_ms` | receive-block handler (client.py) | `bitswap_blocks_received_total`, `bitswap_block_receive_latency_ms` (hist), `bitswap_block_received_bytes` (hist) |
| `block_sent: cid, peer_id, size_bytes` | outbound block path (message_queue.py flush) | `bitswap_blocks_sent_total`, `bitswap_block_sent_bytes` (hist) |
| `message_sent: peer_id, kind (wantlist\|blocks\|presence\|control), entries, bytes` | `BitswapMessageQueue._flush` (message_queue.py:200) | `bitswap_message_sent_total{kind}`, `bitswap_message_sent_bytes` (hist) |
| `message_received: peer_id, kind, entries, bytes` | inbound read loop | `bitswap_message_received_total{kind}`, `bitswap_message_received_bytes` (hist) |
| `session_new` / `session_end: cid, peer_id` | `BitswapSession` start/stop (session.py) | `bitswap_active_sessions` (gauge) |
| `provider_query: cid, peers_found, duration_ms, success` | `provider_query.py` (ProviderQueryManager) | `bitswap_provider_queries_total{result}`, `bitswap_provider_queries_duration_ms` |
| `error: peer_id, kind` | error paths (dial-back avoidance, GO_AWAY, oversized block — client.py errors.py) | `bitswap_errors_total{kind}` |
| `peer_connected / peer_disconnected: peer_id, protocol_version` | `BitswapClient` INotifee hooks (client.py:234-290 — already fires on lifecycle) | `bitswap_peers` (gauge) |

Emit site access: `BitswapClient` holds `self.host` → `host.get_event_bus()`. `BitswapMessageQueue` gets an optional `event_bus` param (constructed in `client.get_or_create_message_queue`, client.py:122).

### 4.3 Peer Discovery modules

New `DiscoveryEvent` in `libp2p/discovery/events/events.py`:

| Event | Emit site | Prometheus metric |
|---|---|---|
| `peer_discovered: peer_id, addr_count, source (mdns\|bootstrap\|random_walk\|rendezvous)` | mDNS `add_service` (listener.py:74 — today only feeds `peerDiscovery`); bootstrap `_handle_peer_info` (bootstrap.py:269); random walk on result | `discovery_peer_discovered_total{source}` |
| `peer_lost: peer_id, source` | mDNS `remove_service` (listener.py:88) | `discovery_peer_lost_total{source}` |
| `bootstrap_connect_attempt: peer_id, success, duration_ms` | `BootstrapDiscovery._connect_to_peer` (bootstrap.py:259) | `discovery_bootstrap_connect_total{result}`, `discovery_bootstrap_connect_duration_ms` (hist) |
| `bootstrap_peer_removed: peer_id, reason` | consecutive-failure removal (bootstrap.py) | `discovery_bootstrap_peer_removed_total{reason}` |
| `random_walk: peers_found, duration_ms, success` | `RandomWalk.perform_random_walk` (random_walk.py:63) | `discovery_random_walk_total{result}`, `discovery_random_walk_peers_found` (hist), `discovery_random_walk_duration_ms` |
| `rendezvous_register / rendezvous_discover: outcome` | rendezvous module (if enabled) | `discovery_rendezvous_register_total{result}`, `discovery_rendezvous_discover_total{result}` |
| `known_peers: source, count` (snapshot) | periodic in host | `discovery_known_peers{source}` (gauge) |

**Relationship with the existing `peerDiscovery` singleton:** keep the singleton exactly as-is for app-facing callbacks (examples rely on it — `examples/mDNS/mDNS.py:44`, `examples/bootstrap/bootstrap.py:73`). The bus emission is **additional**: mDNS/bootstrap emit into the host bus (for metrics) *and* keep calling `peerDiscovery.emit_peer_discovered` (for apps). One line each at the existing call sites.

Wiring: mDNS has `host`; bootstrap gets an `event_bus` constructor param from `BasicHost`; random walk has `host`.

### 4.4 Pubsub (`libp2p/pubsub/`) — extend `GossipsubEvent`

| Event | Emit site | Metric |
|---|---|---|
| inbound `received/publish/subopts/control/message_size` (existing) | read loop `pubsub.py:571` | existing counters (keep) |
| `publish_out: topic, peers_sent, message_size` | `Pubsub.publish` | `gossipsub_publish_out_total`, `gossipsub_publish_out_bytes` (hist) |
| `subscription_change: topic, peer_id, subscribe` | `handle_subscription` / `subscribe` | `gossipsub_subscription_changes_total{action}` |
| `validation: topic, result (accept\|ignore\|reject)` | validator pipeline (pubsub.py validators) | `gossipsub_validation_total{result}` |
| `mesh_size: topic, n` (snapshot) | gossipsub maintenance loop (gossipsub.py:2483 area) | `gossipsub_mesh_size{topic}` (gauge) |
| `peer_joined / peer_left: topic` | mesh join/leave (gossipsub.py:584, 824) | `gossipsub_peer_joined_total{topic}`, `gossipsub_peer_left_total{topic}` |

### 4.5 Swarm (`libp2p/network/`) — extend `SwarmEvent` + add gauges

| Event | Emit site | Metric |
|---|---|---|
| existing 4 dial/conn counters | swarm.py:689, 888, 1722, 1775, 1800, 1821 | keep |
| `conn_opened / conn_closed: peer_id, direction` | `add_conn` / `_cleanup` / `notify_disconnected` | `swarm_connections` (gauge), `swarm_connections_total{result}` |
| `stream_opened / stream_closed: peer_id, protocol` | `notify_opened_stream` / `notify_closed_stream` | `swarm_streams_opened_total`, `swarm_streams` (gauge) |
| `listener_added / listener_removed: multiaddr` | listen/close paths | `swarm_listeners` (gauge) |

### 4.6 Ping — leave as-is

`PingEvent` + `PingMetrics` (rtt histogram, failure counter) are complete. Only change: switch the emit site (host/ping.py:251) from `stream.metric_send_channel` to `host.get_event_bus().emit(...)` (the ping service holds no host today — add an optional `event_bus` param to `PingService`, wired from `BasicHost`).

### 4.7 rcmgr — recommendation: keep separate (for now)

`rcmgr` already ships its own optimized `Metrics` + `PrometheusExporter` (rcmgr/metrics.py, prometheus_exporter.py) with its own enable flags and exporter thread. Bridging it into the event bus would double-instrument. **Recommendation:** leave rcmgr standalone; add a thin optional `RcmgrSnapshotListener` later (periodic `bus.emit(RcmgrSnapshot(...))`) only if a unified scrape endpoint is desired. Same for the relay `performance_tracker` singleton (relay/circuit_v2/performance_tracker.py) — it already has `export_metrics()`; optionally expose via a listener later.

---

## 5. The Metrics Consumer — `MetricsListener`

**New `libp2p/metrics/listener.py`:**

```python
class MetricsListener(IEventListener):
    def __init__(self, metrics: Metrics | None = None) -> None:
        self.metrics = metrics or Metrics()   # per-module collectors

    async def handle_event(self, event: Any) -> None:
        match event:
            case PingEvent():      self.metrics.ping.record(event)
            case GossipsubEvent(): self.metrics.gossipsub.record(event)
            case KadDhtEvent():    self.metrics.kad_dht.record(event)
            case SwarmEvent():     self.metrics.swarm.record(event)
            case BitswapEvent():   self.metrics.bitswap.record(event)      # new
            case DiscoveryEvent(): self.metrics.discovery.record(event)    # new
```

- `Metrics` gains `bitswap: BitswapMetrics` and `discovery: DiscoveryMetrics` collectors (`libp2p/metrics/bitswap.py`, `libp2p/metrics/discovery.py`), following the existing collector pattern (`metrics/kad_dht.py`, `metrics/swarm.py`).
- Convenience: `Metrics.attach(event_bus)` → `event_bus.register_listener(MetricsListener(self))`.
- Keep `Metrics.start_prometheus_server(recv_channel)` (used by `examples/metrics/runner.py:57` and `tests/core/observability/test_prometheus_metrics.py:112`) working through the compat bridge until deprecated.
- **Bonus listener** (cheap, high value): `LoggingMetricsListener` that emits `logger.info/debug` per event — invaluable for the py-ipfs-lite staging debugging we did (no prometheus scrape needed to see DHT/bitswap activity).

## 5.1 Fix the high-cardinality label problem (do this in the same PR)

Every existing counter uses `labelnames=["peer_id"]`. On a busy node this explodes (peerstore of 2k+ peers → 2k label sets per counter, unbounded). go-libp2p does not label by peer id.

**Recommendation:** move `peer_id` out of labels:
- keep it as an **event field** (for log listeners, debugging);
- label by bounded dimensions only: `direction`, `protocol`, `kind`, `result`, `source`, `topic`, `reason`.
- if per-peer tracking is genuinely needed, expose it via the debug endpoints (like `debug/routing_table`) or a separate bounded set, not prometheus labels.

---

## 6. Wiring & Lifecycle Changes (files touched)

| File | Change |
|---|---|
| `libp2p/events/bus.py` (new) | `EventBus`, `IEventListener` |
| `libp2p/events/__init__.py` (new) | re-exports |
| `libp2p/abc.py` | add `IHost.get_event_bus()` abstract (near line 2208); keep `get_metrics_recv_channel()` as deprecated |
| `libp2p/host/basic_host.py` | create/own `EventBus`; `start()/stop()` in `run()`; pass bus to `BootstrapDiscovery`, `PingService`, mDNS; `get_event_bus()` |
| `libp2p/__init__.py` | `new_host`: always create bus; `enable_metrics` → register `ChannelBridgeListener` into old recv channel (compat) |
| `libp2p/network/events.py` (new) | `SwarmEvent` moves here (re-export from `metrics/swarm.py`) |
| `libp2p/network/swarm.py` | emit via bus (in addition to / instead of channel); new conn/stream/listener events |
| `libp2p/kad_dht/kad_dht.py` | extend `KadDhtEvent`; emit outbound + operational events; keep inbound emit |
| `libp2p/kad_dht/peer_routing.py` | emit lookup/find_peer/refresh events |
| `libp2p/kad_dht/provider_store.py`, `value_store.py` | emit provide/find_providers/republish events |
| `libp2p/bitswap/events.py` (new), `client.py`, `message_queue.py`, `session.py`, `provider_query.py` | `BitswapEvent` + emit points |
| `libp2p/pubsub/pubsub.py`, `gossipsub.py` | extend `GossipsubEvent`; outbound emit |
| `libp2p/discovery/events/events.py` (new) | `DiscoveryEvent` |
| `libp2p/discovery/mdns/listener.py`, `bootstrap/bootstrap.py`, `random_walk/random_walk.py` | emit `DiscoveryEvent` (+ keep singleton callbacks) |
| `libp2p/host/ping.py` | emit via bus |
| `libp2p/metrics/listener.py` (new), `metrics.py`, `metrics/bitswap.py` (new), `metrics/discovery.py` (new) | `MetricsListener`, new collectors, `Metrics.attach()` |
| `examples/metrics/runner.py`, `examples/mDNS/mDNS.py`, `examples/bootstrap/bootstrap.py` | migrate to `bus.register_listener(...)` / `Metrics.attach()` |
| `libp2p/metrics/prometheus.yml` | add new metric groups |

---

## 7. Testing Strategy

1. **EventBus unit tests** (`tests/core/events/test_event_bus.py`):
   - register/remove/duplicate-register; fan-out to N listeners;
   - isolation: raising listener doesn't stop other listeners or the emitter;
   - slow listener: queued listener never blocks `emit` (test with a listener that sleeps);
   - drop-on-full: fill a tiny buffer, assert drop counter increments, emitter not blocked;
   - start/stop lifecycle: consumer task drains correctly; events emitted before `start()` are not lost for queued listeners (or documented as dropped).
2. **Per-module emit tests** (mirror `tests/core/network/test_notify.py` style): a recording listener on the bus asserts events fired for: DHT lookup/provide/find_providers/put/get_value (2-node integration), bitswap want→block roundtrip, mDNS/bootstrap peer discovery, pubsub publish/validation, swarm dial/conn.
3. **Metrics recording tests**: extend `tests/core/observability/test_prometheus_metrics.py` with `BitswapMetrics`/`DiscoveryMetrics` record tests; keep the existing dispatch test (`test_metrics_pipeline_dispatches_ping`).
4. **Backward-compat tests**: with `enable_metrics=True`, the old `metric_recv_channel` still receives events (bridge works); `start_prometheus_server` still functions.
5. **Performance regression**: reuse the `test_notifee_performance.py` pattern — assert `emit` with 0/1/10 listeners adds negligible overhead on a hot loop (e.g. 100k emits < X ms); assert a busy protocol handler is never blocked by a full queue.

---

## 8. Rollout Phases (each lands green, `make lint` + full suite)

| Phase | Contents | Exit criteria |
|---|---|---|
| **0** | This plan + event taxonomy review with maintainers | plan approved; event/metric names agreed |
| **1** | `EventBus` core + `libp2p/events/` + host wiring + bridge listener; **no behavior change** | bus unit tests green; old metrics example still works unchanged |
| **2** | Migrate existing emitters to the bus: swarm, kad-dht inbound, pubsub inbound, ping (via bridge) | existing prometheus tests pass unchanged; counts identical |
| **3** | Bitswap events + `BitswapMetrics` | new tests; 2-node block-transfer test shows counters |
| **4** | Discovery events (mDNS, bootstrap, random walk, rendezvous) + `DiscoveryMetrics` | new tests; mDNS/bootstrap examples still function |
| **5** | Outbound DHT events + pubsub outbound + snapshot gauges | 2-node DHT tests assert outbound counters |
| **6** | `MetricsListener` + `Metrics.attach()`; migrate examples/tests; deprecate channel API; remove `metric_send_channel` from `INetStream` | no references to `metric_send_channel` outside deprecation shims |
| **7** | Cardinality fix (drop `peer_id` labels), `prometheus.yml`, docs (`docs/libp2p.events.rst`), optional LoggingMetricsListener, perf validation on staging (py-ipfs-lite) | staging scrape shows all metric groups; dashboard renders |

---

## 9. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Event flooding on hot paths (bitswap block loops) slows node | drop-on-full queues; emit is `send_nowait`; measure in Phase 3 perf test |
| Breaking the existing metrics example/tests during migration | bridge listener keeps old channel path byte-for-byte working until Phase 6 |
| Multiple nodes per process (tests, apps) sharing one bus | bus is per-host; `peerDiscovery` singleton stays app-only and is not used for metrics |
| Listener crashes/blocking take down modules | consumer-task isolation (copy of `Swarm._notify` semantics) + per-listener queues |
| High-cardinality prometheus labels | §5.1: bounded labels only; `peer_id` stays an event field |
| Event class churn breaks user imports | events keep living in home modules; new ones additive; `SwarmEvent` re-exported |
| Discovery modules lack host/bus access (bootstrap, ping) | explicit `event_bus` constructor param wired from `BasicHost` (small, contained) |

---

## 10. Open Questions for Maintainers

1. **Bus placement:** per-host (recommended) vs module-level singleton like `peerDiscovery`? Per-host is safer for multi-node processes and tests; singleton is more convenient for user code. (Can do both: per-host bus + a module-level convenience `get_default_event_bus()` for standalone apps.)
2. **Emit semantics:** queued+drop (recommended, go-libp2p-style) vs inline-sync fan-out vs block-on-full (reliable delivery, risky hot path)?
3. **Cardinality:** OK to remove `peer_id` labels from existing counters (behavior change in metric names/labels — technically breaking for existing dashboards)?
4. **Scope:** should rcmgr + relay performance_tracker bridge into the bus in this effort, or stay separate (recommended: separate, optional later)?
5. **Auto-wiring:** should `enable_metrics=True` auto-attach `MetricsListener` in `new_host`, or keep it app-driven (current examples create `Metrics()` themselves)?
6. **Deprecation timeline:** keep the channel API for one release cycle, or remove in the same PR as the migration?

---

*Prepared from verified code analysis (Aug 2026): INotifee fan-out at `libp2p/network/swarm.py:2691-2730`; existing channel pipeline at `libp2p/__init__.py:750-815`; emit sites at `kad_dht.py:1208`, `pubsub.py:571`, `swarm.py:689/888/1722/1775/1800/1821`, `host/ping.py:251`; singleton discovery events at `discovery/events/peerDiscovery.py` + `mdns/listener.py:74` + `bootstrap/bootstrap.py:269`.*
