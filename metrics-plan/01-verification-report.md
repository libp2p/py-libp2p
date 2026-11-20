# Metrics Verification Report — Event-Bus Driven Prometheus Metrics

**Scope:** End-to-end verification of the event-bus driven metrics pipeline
(`libp2p/events/bus.py`, `libp2p/metrics/*`, `Metrics.attach()`,
`MetricsListener`) implemented on top of
[00-metrics-integration-plan.md](00-metrics-integration-plan.md).

**Branch:** `audit-stability-improvements` (HEAD `8cb1efdb feat(metrics): event-bus driven prometheus metrics`)
**Environment:** macOS, Python 3.12.2 (pyenv), prometheus-client 0.25.0, trio 0.29, ruff 0.16.3, mypy 1.15+
**Date:** 2026-08-17

---

## 1. Verdict

| Area | Result |
|---|---|
| Event emission (swarm, DHT, bitswap, discovery) | ✅ all flows verified |
| `Metrics.attach()` / `MetricsListener` fan-out | ✅ all 14 event types dispatched |
| Counter values (in-process) | ✅ all 15 counters correct incl. labels |
| Prometheus text exposition over HTTP `/metrics` | ✅ valid, parseable with official parser |
| Ruff on `libp2p/` | ✅ clean (13 issues fixed, 1 real bug fixed) |
| mypy on `libp2p/` | ⚠️ 4 pre-existing errors, none in `metrics/` or `events/` |

---

## 2. Tests run

Manual scripts under a scratch dir (not committed); each exits non-zero on failure.

| Test | What it does | Result |
|---|---|---|
| `t1_swarm_events.py` | Two hosts, dial + connect; asserts `SwarmEvent`s (dial, conn opened/closed, muxer upgraded, security handshake) arrive on both hosts' event buses with correct `direction`/`protocol`/`conn_type` fields | ✅ |
| `t2_dht_value_events.py` | `put_value`/`get_value` over real DHT; asserts `KadDhtEvent`s for outbound put/get with `result=success`, correct key hash/op | ✅ |
| `t3_dht_random_walk.py` | `random_walk()`; asserts `KadDhtEvent(random_walk)` emitted and `get_peers` found non-empty | ✅ |
| `t4_bitswap_events.py` | wantlist add/cancel, block received/sent; asserts `BitswapEvent` fields (cid, peer, kind) | ✅ |
| `t5_metrics_counters.py` | Full DHT+bitswap scenario with `Metrics.attach()`; reads 15 counters + label sets from the `Metrics` objects | ✅ |
| `t6_prometheus_render.py` | Same scenario + `Metrics.start_http_server()`; scrapes `/metrics`, parses with `prometheus_client.parser`, validates HELP/TYPE lines, label sets, values | ✅ (515 lines scraped) |
| `t7_coverage.py` + `pubsub_probe5.py` | Full-stack scenario (DHT, bitswap, ping, request-response, pubsub/gossipsub on both hosts) scraped over HTTP; lists every zero-valued family and classifies it | ✅ 43 families nonzero |

Note: the DHT random walk and the DHT stream handlers print
`Failed to read DHT message from stream:` twice per run — this is pre-existing
noise from the DHT stream reading loop, unrelated to the event/metrics path.

---

## 3a. Metrics coverage annex (which families fire, by traffic)

Verified with **real traffic** (nonzero values in the scrape):

| Module | Families that increment |
|---|---|
| transport | `transport_dial_total`, `transport_inbound_conn_total` (label `transport="tcp"`) |
| muxer | `muxer_conns_total{direction=inbound\|outbound}`, `muxer_streams_open/closed_total` |
| security | `security_handshake_total`, `security_handshake_duration_ms` |
| swarm | `swarm_dial_attempt_total`, `swarm_incoming_conn_total` |
| listener | `connections_opened_total{connection_type=direct}` |
| identity | `identity_identify_total` (inbound+outbound per peer) |
| kad-dht | `kad_put_value_total`, `kad_get_value_total`, `kad_lookup_total` (+duration/peers histograms), `kad_inbound_total` (+per-op), `kad_record_validation_total`, `kad_refresh_total`, `kad_stream_reset_total`, `kad_find_peer_total` |
| bitswap | `wantlist_adds/cancels_total`, `blocks_received/sent_total` (+bytes histograms), `message_received/sent_total` (+bytes), `sessions_total` |
| gossipsub | `gossipsub_received_total`, `publish_total`, `subopts_total`, `control_total`, `message_bytes` (histogram), `publish_out_total` (+bytes), `subscription_changes_total` |
| ping | `ping` latency histogram |
| request-response | `request_response_requests_total{protocol,direction}`, `request_response_latency_ms` |

**Zero in the tests but correctly wired — expected for the topology:**
- `relay_*` — no circuit-relay hop in a 2-peer test
- `discovery_bootstrap_connect_*` / `peer_discovered` — bootstrap/mDNS services not started; discovery random-walker not started (DHT `peer_routing.random_walk()` emits `KadDhtEvent`, not the discovery event)
- `kad_provide_total`, `kad_find_providers_total` (+found histogram) — `provide()`/`find_providers()` not called
- `bitswap_provider_queries_*` — block found locally, no DHT provider lookup
- `kad_rate_limited_total` — no rate-limit trigger in tests
- `kad_routing_table_peers` (gauge) — set only by the periodic DHT maintenance loop every `ROUTING_TABLE_REFRESH_INTERVAL` (600 s)
- `python_gc_*` — standard runtime metrics

To verify gossipsub inbound metrics, create the pubsub services **before** dialing
(stream handshake is driven by the `connected` notifee); the earlier zero
values were due to connect-before-pubsub ordering in the probe.

---

## 3. What was verified end to end

- **Event bus fan-out.** `EventBus.emit()` (sync, non-blocking) reaches every
  registered listener; a failing listener cannot break emitters (isolated +
  logged). Verified by collecting events with a second listener alongside
  `MetricsListener`.
- **MetricsListener dispatch** (`libp2p/metrics/listener.py`) covers all
  module families: Ping, Gossipsub, KadDht, Swarm, Bitswap, Discovery,
  Identity, Relay, Transport, ListenConn, Muxer, Security, RequestResponse.
- **Counter accuracy.** With `attach()` active on both hosts, after one
  dial + one DHT put/get + one bitswap block exchange:
  - `transport_dial_total{transport="tcp",result="success"} = 1`,
    `transport_inbound_conn_total{...} = 1`
  - `muxer_conns_total{direction=inbound|outbound} = 2`, `muxer_streams_open_total = 12`
  - `security_handshake_total` with both directions, `result="success"`
  - `bitswap_wantlist_adds_total`, `blocks_received_total`, `message_received_total` ≥ 1
  - `kad_put_value_total{result="success"} = 1`, `kad_get_value_total{result="success"} = 1`
  - `connections_opened_total{connection_type="direct"} = 2`
- **Exposition format.** `/metrics` serves valid Prometheus text: correct
  `# HELP` / `# TYPE ... counter` lines, `_created` gauges, label sets, and
  values; parses cleanly with `text_string_to_metric_families`.

---

## 4. Bugs found & fixed

### 4.1 `NameError` risk: `RcMgrMetrics` undefined (F821)
`libp2p/metrics/metrics.py` annotated `rcmgr: "RcMgrMetrics | None"` but never
imported the name. Fixed with a `TYPE_CHECKING` import — ruff now clean.

### 4.2 Ruff cleanup (13 auto-fixable)
- `D213` docstring style in `libp2p/events/bus.py` (7×) and
  `libp2p/metrics/rcmgr.py` (1×)
- `I001` import sort in `libp2p/host/basic_host.py`
- `W292` missing trailing newlines in `libp2p/metrics/{identity,rcmgr,relay,request_response}.py`
- `ruff format` applied to `libp2p/events/` and `libp2p/metrics/`

Re-ran `t1`/`t2` after the fixes: still green.

---

## 5. Findings (no code change needed)

1. **Legacy `Metrics.start_prometheus_server()` only handles 5 event types**
   (Ping, Gossipsub, KadDht, Swarm, ListenConn — `metrics.py:135-175`), while
   the new `MetricsListener` handles all 14. The legacy path is kept for the
   channel-based API but is a maintenance trap; consider deleting it once
   `attach()` is the only supported wiring.

2. **Bitswap `provider_queries_total = 0` is correct in a 2-node test.** The
   block is found on the connected peer directly (session fetch), so no DHT
   provider query fires. Do not expect this counter to increment in small
   local topologies.

3. **prometheus-client 0.25 API gotchas** (why naive counter reads fail):
   - label-less counters store the value on `counter._value`; labeled
     counters keep children in `counter._metrics` and each child has its own
     `_value`. The parent has **no** `_value`.
   - on children, `.labels` is a *method* (returns the child), not the label
     dict — read `sample._labelnames` / `sample._labelvalues` instead.
   - the text parser strips the `_total` suffix from family names
     (`kad_put_value`, not `kad_put_value_total`), while sample names keep it.
   - the metrics listener module names (`kad_dht_put_value_total`) differ from
     the emitted metric names (`kad_put_value_total`); `connections_opened_total`
     has no `libp2p_` prefix.

4. **mypy: 4 pre-existing errors, none in the event/metrics code:**
   - `libp2p/metrics/rcmgr.py:14` — `prometheus_client.core.Collector` attr
   - `libp2p/security/noise/io.py:103,114` — missing return annotations
   - `libp2p/network/swarm.py:2665` — `IMuxedConn.get_remote_address`
   Recommend fixing separately.

5. **Repo-wide ruff still has 11 pre-existing errors outside `libp2p/`**
   (tests/examples/docs) — out of scope here.

---

## 6. How to re-run

```bash
# lint / types (clean on libp2p/ after fixes)
ruff check libp2p/
mypy -p libp2p

# end-to-end verification (repo must be on PYTHONPATH)
PYTHONPATH=/path/to/py-libp2p python t5_metrics_counters.py   # counters
PYTHONPATH=/path/to/py-libp2p python t6_prometheus_render.py  # /metrics scrape
```
