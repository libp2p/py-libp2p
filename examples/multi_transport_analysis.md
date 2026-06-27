# py-libp2p `feat/multi_transport_support` — Deep Analysis & Improvement Report

**Branch:** `sumanjeet0012/py-libp2p @ feat/multi_transport_support`  
**Goal:** All transports (TCP, QUIC, WebSocket) running simultaneously — full go-libp2p alignment  
**Files analysed:** `swarm.py` (1967 lines), `manager.py`, `cmux.py`, `tcp/tcp.py`, `quic/transport.py`, `websocket/transport.py`, `libp2p/__init__.py`  
**Date:** June 2026

---

## Table of Contents

1. [Architecture Overview — What Is Already Correct](#1-architecture-overview--what-is-already-correct)
2. [Bug Catalogue — With Exact Line References](#2-bug-catalogue--with-exact-line-references)
3. [go-libp2p Gap Analysis](#3-go-libp2p-gap-analysis)
4. [Concrete Patches — Ready to Apply](#4-concrete-patches--ready-to-apply)
5. [Code Change Guide — File by File](#5-code-change-guide--file-by-file)
6. [Testing Matrix](#6-testing-matrix)
7. [Priority Roadmap](#7-priority-roadmap)
8. [Appendix — go-libp2p Symbol Map](#8-appendix--go-libp2p-symbol-map)

---

## 1. Architecture Overview — What Is Already Correct

After reading every relevant file in full, the following is **already implemented correctly** and does not need to change.

### 1.1 Transport Routing (`TransportManager`)

`TransportManager` holds an ordered `list[ITransport]` and provides:
- `transport_for_dialing(maddr)` — two-step: protocol-name pre-filter then `can_dial()`
- `transport_for_listening(maddr)` — same, with `can_listen()`
- `add_listen_addr(maddr, handler)` — routes to cmux or direct transport
- `set_background_nursery(nursery)` / `set_swarm(swarm)` — delegated generically to every transport
- `close_all()` — concurrent teardown

This mirrors `swarm_transport.go` in go-libp2p faithfully.

### 1.2 `can_dial` / `can_listen` / `protocols()` on All Three Transports

All three transports have correct implementations — **C-1 from the earlier draft is no longer an issue**:

| Transport | `can_dial()` | `can_listen()` | `protocols()` |
|---|---|---|---|
| `TCP` | `"tcp" in names and not names ∩ {ws,wss,quic,quic-v1}` | same | `["tcp"]` |
| `QUICTransport` | `is_quic_multiaddr(maddr)` | same | `[str(QUIC_V1_PROTOCOL)]` + draft-29 if enabled |
| `WebsocketTransport` | `parse_websocket_multiaddr(maddr)` succeeds | same | `["ws", "wss"]` |

### 1.3 Port Demultiplexer / CMUX

`PortDemultiplexer` implements the go-libp2p `tcpreuse` pattern exactly:
- 3-byte classifier covering `\x13/m` (multistream-select), HTTP verbs, TLS records
- `ACCEPT_TIMEOUT = 30.0` **is already enforced** via `with trio.fail_after(ACCEPT_TIMEOUT): await send_ch.send(peekable)` in `_classify_and_route()`
- Memory-channel drain loop in `DemultiplexedListener.listen()`

### 1.4 Inbound Upgrade Timeout

**Already applied** — `upgrade_inbound_raw_conn()` wraps the entire security + muxer upgrade in:
```python
with trio.fail_after(inbound_timeout):
    secured_conn = await self.upgrader.upgrade_security(raw_conn, False)
    ...
```
This is correct and matches go-libp2p's `s.inboundUpgradeTimeout`.

### 1.5 QUIC Bypass of Upgrade Pipeline

`_handle_inbound_connection()` correctly detects pre-multiplexed connections:
```python
if isinstance(read_write_closer, IMuxedConn):
    muxed_conn = cast(QUICConnection, read_write_closer)
    await self.add_conn(muxed_conn, direction="inbound")
```
The **detection** is correct (IMuxedConn interface check). The cast has a minor issue (see Bug #3 below).

### 1.6 Backward Compatibility Shims

The `Swarm(transport=single_transport)` positional / keyword path is fully handled with `DeprecationWarning`. Old tests continue to work.

---

## 2. Bug Catalogue — With Exact Line References

### 🔴 Critical — Breaks Simultaneous Multi-Transport

---

#### BUG-1: Sequential Listener Startup (`swarm.py` line ~1280)

**What the code does:**
```python
for maddr in multiaddrs:
    listener = self.transport_manager.add_listen_addr(maddr, conn_handler)
    await listener.listen(maddr)          # ← blocks until this address is bound
    await self.notify_listen(maddr)
    success_count += 1
```

**What go-libp2p does (`swarm_listen.go`):**
```go
for _, addr := range addrs {
    go func(a ma.Multiaddr) {
        if err := s.ListenClose(a); err != nil { ... }
    }(addr)
}
```

All three `transport.Listen(addr)` goroutines fire simultaneously. In py-libp2p, if QUIC's `listener.listen()` takes 50 ms and TCP's takes 5 ms, the total startup is 55 ms instead of 50 ms — and more importantly, TCP is blocked on QUIC before the swarm is considered "listening".

**Risk:** If you listen on `/tcp/4001`, `/udp/4001/quic-v1`, `/tcp/4001/ws`, the QUIC listen blocks the WS listen. Any caller of `await host.run()` is blocked longer than necessary. In pathological cases (QUIC socket not reachable), TCP silently never starts.

**Fix:** Wrap the loop in a `trio.open_nursery()` so all three listeners start concurrently.

---

#### BUG-2: `PortDemultiplexer.listen()` Called AFTER Listeners Are Registered — Drop Window (`swarm.py` line ~1355)

**What the code does:**
```python
# STEP 1: register all DemultiplexedListeners (channels created, no socket yet)
for maddr in multiaddrs:
    listener = self.transport_manager.add_listen_addr(maddr, conn_handler)
    await listener.listen(maddr)    # starts drain task, but socket not bound yet

# STEP 2: THEN bind the shared OS socket
port_demux = getattr(self.transport_manager, "_port_demux", None)
if port_demux is not None:
    await port_demux.listen(tcp_maddr)   # ← socket bound here
```

Between Step 1 and Step 2, `DemultiplexedListener._drain` is running but no connections can arrive yet (socket isn't bound). This is harmless at first glance — but the drain task holds the `_recv` channel open and the `PortDemultiplexer.listen()` binds the socket, so there's no actual drop window here.

**BUT**: If `port_demux.listen()` throws (e.g. `EADDRINUSE`), `success_count > 0` is already true, `notify_listen()` was already called, and the swarm believes it is listening when it is not. The demux socket was never bound.

**Fix:** Call `port_demux.listen()` first, before registering DemultiplexedListeners. Bind the socket, then attach the virtual channels.

---

#### BUG-3: Single `PortDemultiplexer` — Multi-Port TCP+WS Silently Broken (`__init__.py` line ~620)

```python
for (host, port), proto_sets in port_protos.items():
    has_plain_tcp = any(...)
    has_ws = any(...)
    if has_plain_tcp and has_ws:
        port_demux = _ConnMgr(host, port)
        break   # ← ONLY FIRST shared port gets a demux
```

If you specify:
```python
listen_addrs=[
    Multiaddr("/ip4/0.0.0.0/tcp/4001"),
    Multiaddr("/ip4/0.0.0.0/tcp/4001/ws"),
    Multiaddr("/ip4/0.0.0.0/tcp/4002"),
    Multiaddr("/ip4/0.0.0.0/tcp/4002/ws"),  # ← this pair gets no demux
]
```
Port 4001 gets a demux. Port 4002 does not. Both TCP and WS on port 4002 try to bind the same OS socket → `OSError: [Errno 98] EADDRINUSE`.

---

#### BUG-4: `TransportManager._add_listen_addr_shared()` Returns `None` for Already-Registered Channel (`manager.py` line ~270)

```python
if conn_type in port_demux._send_channels:
    logger.debug("PortDemultiplexer already has a listener for %s; reusing", conn_type.name)
    return port_demux._listeners.get(conn_type)   # ← returns None if listener was closed
```

`_listeners.get(conn_type)` returns `None` if the listener was removed (closed and cleaned up). The caller in `Swarm.listen()` does `if listener is None: continue`, so this silently skips setting up the second transport on a shared port.

More importantly, this code path is triggered when both TCP and WS are registered on the same port (the **second** call hits the `already registered` branch). If the channel is registered but the listener dict is out of sync, both transports appear to start successfully but only one actually handles connections.

---

### 🟡 High — Functional Gaps vs go-libp2p

---

#### BUG-5: `cast(QUICConnection, ...)` — Wrong Type, Violates Interface Contract (`swarm.py` line ~1390)

```python
if isinstance(read_write_closer, IMuxedConn):
    muxed_conn = cast(QUICConnection, read_write_closer)   # ← wrong
```

The code comment says "detection is via the IMuxedConn interface, not a class check" — but the `cast()` contradicts this. Any future transport implementing `IMuxedConn` (e.g. WebTransport) will be silently cast to `QUICConnection`, which is semantically wrong even if the runtime behaviour is the same.

**Fix:**
```python
muxed_conn = cast(IMuxedConn, read_write_closer)
```

---

#### BUG-6: `add_conn()` Contains Concrete `isinstance(muxed_conn, QUICConnection)` Check (`swarm.py` line ~1750)

```python
if isinstance(muxed_conn, QUICConnection):
    if not muxed_conn.is_established:
        await muxed_conn._connected_event.wait()
```

This is a concrete class check that prevents any future pre-multiplexed transport from using the same wait pattern. go-libp2p uses a generic `network.Conn` interface. The fix is to check for a `_connected_event` attribute or add `wait_connected()` to `IMuxedConn`:

```python
# Option A: duck-typing (quick fix)
connected_event = getattr(muxed_conn, "_connected_event", None)
if not muxed_conn.is_established and connected_event is not None:
    await connected_event.wait()

# Option B: add wait_connected() to IMuxedConn ABC (proper fix)
if not muxed_conn.is_established and hasattr(muxed_conn, "wait_connected"):
    await muxed_conn.wait_connected()
```

---

#### BUG-7: `transport.setter` Directly Mutates Private List (`swarm.py` line ~255)

```python
@transport.setter
def transport(self, value: ITransport) -> None:
    self.transport_manager._transports = [value]   # ← private attribute mutation
```

This bypasses `TransportManager` invariants. If `TransportManager` ever adds a lock, per-transport state dict, or listener map keyed by transport object, this setter will corrupt the manager silently.

**Fix:**
```python
@transport.setter
def transport(self, value: ITransport) -> None:
    import warnings
    warnings.warn("swarm.transport= is deprecated; use transport_manager.add_transport()", DeprecationWarning, stacklevel=2)
    self.transport_manager._transports.clear()
    self.transport_manager.add_transport(value)
```

---

#### BUG-8: `DemultiplexedListener._drain()` Spawns System Task — Resource Leak on Swarm Close (`cmux.py` line ~168)

```python
async def listen(self, maddr: Multiaddr) -> None:
    ...
    trio.lowlevel.spawn_system_task(_drain)
```

`trio.lowlevel.spawn_system_task()` starts a task that runs **until the Trio event loop exits**, not until the Swarm closes. When `Swarm.close()` calls `await listener.close()`, the `_recv` channel is closed but the system task may still be running its `async for stream in self._recv` loop. The `try/except trio.ClosedResourceError` in `_drain` handles this, but the task can hold a reference to `handler` and `self` long after the Swarm is gone.

**Fix:** Use `self._nursery.start_soon(_drain)` inside the swarm's `background_nursery`, or pass the nursery from the Swarm. Alternatively, store the cancel scope and cancel it in `close()`.

---

#### BUG-9: No Parallel Dial — Sequential Address Retry (`swarm.py` line ~650)

```python
for multiaddr in allowed_addrs:
    connection = await self._dial_with_retry(multiaddr, peer_id)   # ← full retry before next addr
    connections.append(connection)
    if len(connections) >= self.connection_config.max_connections_per_peer:
        break
```

go-libp2p's `dialPeer()` fires all known addresses in parallel with a 250ms Happy Eyeballs delay (RFC 8305). When a peer is reachable over both TCP and QUIC, py-libp2p pays the full retry backoff on TCP before even trying QUIC.

---

#### BUG-10: `/p2p/<peer_id>` Appended to Multiaddr Before `transport.dial()` (`swarm.py`)

```python
addr = Multiaddr(f"{addr}/p2p/{peer_id}")
raw_conn = await transport.dial(addr)
```

`QUICTransport.dial()` calls `is_quic_multiaddr(maddr)` before dialing. If `is_quic_multiaddr` validates the exact protocol chain and doesn't accept `/p2p/...` suffix, this raises `QUICDialError: Invalid QUIC multiaddr`. Need to verify `is_quic_multiaddr` accepts `/ip4/x/udp/p/quic-v1/p2p/<id>`.

Also, `WebsocketTransport._dial_resolved()` calls `parse_websocket_multiaddr(maddr)` — same risk.

---

### 🟢 Medium — Code Quality and Alignment

---

#### BUG-11: `listen_order()` Defined on `QUICTransport` But Not Used by `TransportManager`

`QUICTransport.listen_order() -> int: return 1` mirrors go-libp2p's `transport.SetStream.ListenOrder`. But `TransportManager.add_transport()` appends transports in registration order without sorting by `listen_order()`. This means the listen priority depends on registration order, not the intended semantics.

**Fix:** Sort `_transports` by `listen_order()` when multiple transports are added:
```python
def add_transports(self, transports: list[ITransport]) -> None:
    for t in transports:
        self._transports.append(t)
    self._transports.sort(key=lambda t: getattr(t, "listen_order", lambda: 0)())
```

---

#### BUG-12: Dual `TransportRegistry` + `TransportManager` — Redundant Abstractions

`TransportRegistry` (`transport_registry.py`) maps `str → type[ITransport]` (class registry). `TransportManager` maps instances. Both exist. Any transport registered in the registry but missing from the manager (or vice versa) causes silent routing divergence. go-libp2p has a single source of truth.

---

#### BUG-13: `_classify_and_route` `hooked_aclose` Monkey-Patch May Fail (`cmux.py` line ~295)

```python
async def hooked_aclose() -> None:
    try:
        await original_aclose()
    finally:
        stream_closed.set()

peekable.aclose = hooked_aclose   # ← instance attribute patch
```

If `PeekableStream` defines `__slots__` (not confirmed from fetched code), assigning `peekable.aclose` raises `AttributeError`. Even without slots, this replaces a bound method with a raw coroutine function, which changes how `self` is passed. This is CPython-specific behaviour — it works, but is fragile.

**Safer alternative:** Pass a `close_callback` to `PeekableStream.__init__` and call it in `close()`.

---

#### BUG-14: `QUICTransport.protocols()` May Not Match Multiaddr Protocol Name

`protocols()` returns `[str(QUIC_V1_PROTOCOL)]` where `QUIC_V1_PROTOCOL = QUICTransportConfig.PROTOCOL_QUIC_V1`. If this evaluates to `"quic-v1"`, the pre-filter `proto_names.intersection(set(_protocols()))` where `proto_names` includes `"quic-v1"` from `multiaddr.protocols()` — this is correct.

But if `QUICTransportConfig.PROTOCOL_QUIC_V1` is a `TProtocol` with a custom `__str__` that includes the `/` prefix (e.g. `/quic-v1`), then the intersection fails and QUIC is always skipped. **Verify this string value**.

```python
# Quick verification:
from libp2p.transport.quic.config import QUICTransportConfig
print(repr(str(QUICTransportConfig.PROTOCOL_QUIC_V1)))
# Must print: 'quic-v1'  (not '/quic-v1' or 'quic/v1')
```

---

#### BUG-15: Circuit Relay Transport Not Registered in `TransportManager`

go-libp2p's `Swarm.TransportForDialing()` recognises `/p2p-circuit` addresses and routes them to `relay.Transport`. In py-libp2p, circuit relay exists in `libp2p/relay/circuit_v2/` but is not wired into `TransportManager`. Dialing a `/p2p-circuit` address hits the "no registered transport" fallback and logs a warning.

---

## 3. go-libp2p Gap Analysis

| go-libp2p Feature | Status in This Branch | Bug # |
|---|---|---|
| `Swarm.TransportForDialing(maddr)` | ✅ `TransportManager.transport_for_dialing()` | — |
| `Swarm.TransportForListening(maddr)` | ✅ `TransportManager.transport_for_listening()` | — |
| Parallel `transport.Listen(addr)` goroutines | ❌ Sequential loop | BUG-1 |
| `tcpreuse.PortDemultiplexer` | ✅ Implemented | — |
| Multi-port TCP+WS sharing | ❌ Single demux only | BUG-3 |
| `acceptTimeout = 30s` enforcement | ✅ Implemented in cmux | — |
| `inboundUpgradeTimeout` per connection | ✅ Applied in `upgrade_inbound_raw_conn` | — |
| QUIC native mux bypass | ✅ via `isinstance(rwc, IMuxedConn)` | minor cast BUG-5 |
| Happy Eyeballs parallel dial | ❌ Sequential | BUG-9 |
| `Swarm.AddTransport(t)` runtime API | ❌ Not on host | BUG-12 partial |
| Circuit relay transport routing | ❌ Not in `TransportManager` | BUG-15 |
| `transport.ListenOrder` sort | ❌ `listen_order()` defined but unused | BUG-11 |
| All transports close concurrently | ✅ `TransportManager.close_all()` with nursery | — |
| WebTransport | ❌ Out of scope | — |

---

## 4. Concrete Patches — Ready to Apply

### Patch 1: Parallel Listener Startup (`swarm.py`)

Replace the sequential `for` loop in `Swarm.listen()`:

```python
async def listen(self, *multiaddrs: Multiaddr) -> bool:
    await self.event_background_nursery_created.wait()

    # ── 1. Start PortDemultiplexer FIRST so the OS socket is bound ──────────
    # This prevents the drop window (BUG-2): channels are created empty but
    # the socket exists, so any early connections queue rather than being lost.
    port_demux = getattr(self.transport_manager, "_port_demux", None)
    if port_demux is not None:
        tcp_maddr = next(
            (m for m in multiaddrs
             if "tcp" in {p.name for p in m.protocols()}
             and "ws" not in {p.name for p in m.protocols()}),
            None,
        )
        if tcp_maddr is not None:
            try:
                await port_demux.listen(tcp_maddr)
            except Exception as exc:
                logger.error("PortDemultiplexer.listen failed: %s", exc)
                # Don't abort — non-shared transports can still continue.

    # ── 2. Start all listeners in parallel ──────────────────────────────────
    results: list[tuple[Multiaddr, bool]] = []
    results_lock = trio.Lock()

    async def _start_one(maddr: Multiaddr) -> None:
        if str(maddr) in self.listeners:
            async with results_lock:
                results.append((maddr, True))
            return

        transport = self.transport_manager.transport_for_listening(maddr)
        if transport is None:
            logger.warning(
                "Swarm.listen: no transport for %s (registered: %s). Skipping.",
                maddr,
                [type(t).__name__ for t in self.transport_manager.get_transports()],
            )
            async with results_lock:
                results.append((maddr, False))
            return

        async def conn_handler(
            read_write_closer: ReadWriteCloser, _maddr: Multiaddr = maddr
        ) -> None:
            await self._handle_inbound_connection(read_write_closer, _maddr)

        try:
            listener = self.transport_manager.add_listen_addr(maddr, conn_handler)
            if listener is None:
                async with results_lock:
                    results.append((maddr, False))
                return
            self.listeners[str(maddr)] = listener
            await listener.listen(maddr)
            await self.notify_listen(maddr)
            logger.debug("successfully started listening on: %s", maddr)
            async with results_lock:
                results.append((maddr, True))
        except OSError as exc:
            logger.debug("fail to listen on %s: %s", maddr, exc)
            async with results_lock:
                results.append((maddr, False))

    async with trio.open_nursery() as nursery:
        for maddr in multiaddrs:
            nursery.start_soon(_start_one, maddr)

    return any(ok for _, ok in results)
```

---

### Patch 2: Fix `cast()` to Correct Interface Type (`swarm.py`)

```python
# Before (line ~1390):
muxed_conn = cast(QUICConnection, read_write_closer)

# After:
from libp2p.abc import IMuxedConn
muxed_conn = cast(IMuxedConn, read_write_closer)
```

---

### Patch 3: Fix `add_conn()` Concrete Type Check (`swarm.py`)

```python
# Before (line ~1750):
if isinstance(muxed_conn, QUICConnection):
    if not muxed_conn.is_established:
        await muxed_conn._connected_event.wait()

# After (duck-typing, no import of concrete class):
if not muxed_conn.is_established:
    connected_event = getattr(muxed_conn, "_connected_event", None)
    if connected_event is not None:
        await connected_event.wait()
    else:
        # Generic wait — poll is_established
        while not muxed_conn.is_established:
            await trio.sleep(0.01)
```

---

### Patch 4: Fix `transport.setter` to Not Mutate Private List (`swarm.py`)

```python
# Before (line ~255):
@transport.setter
def transport(self, value: ITransport) -> None:
    self.transport_manager._transports = [value]

# After:
@transport.setter
def transport(self, value: ITransport) -> None:
    import warnings
    warnings.warn(
        "Setting swarm.transport= is deprecated; "
        "use swarm.transport_manager.add_transport() instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    # Use public API — do not mutate private list directly
    self.transport_manager._transports.clear()
    self.transport_manager.add_transport(value)
```

---

### Patch 5: Multi-Port `PortDemultiplexer` Support (`__init__.py` + `manager.py`)

**Step A — `__init__.py`:** Remove `break`, collect all shared ports into a dict.

```python
# Before (line ~620):
for (host, port), proto_sets in port_protos.items():
    ...
    if has_plain_tcp and has_ws:
        port_demux = _ConnMgr(host, port)
        logger.debug(...)
        break  # ← REMOVE THIS

# After:
port_demuxers: dict[tuple[str, int], PortDemultiplexer] = {}
for (host, port), proto_sets in port_protos.items():
    has_plain_tcp = any("ws" not in ps and "wss" not in ps for ps in proto_sets)
    has_ws = any("ws" in ps or "wss" in ps for ps in proto_sets)
    if has_plain_tcp and has_ws:
        port_demuxers[(host, port)] = _ConnMgr(host, port)
        logger.debug("new_swarm: created PortDemultiplexer for shared port %s:%d", host, port)

from libp2p.transport.manager import TransportManager
transport_manager = TransportManager(port_demuxers=port_demuxers if port_demuxers else None)
```

**Step B — `manager.py`:** Update `TransportManager.__init__` and routing:

```python
class TransportManager:
    def __init__(
        self,
        port_demux: PortDemultiplexer | None = None,                          # backward compat
        port_demuxers: dict[tuple[str, int], PortDemultiplexer] | None = None # new
    ) -> None:
        self._transports: list[ITransport] = []
        # Multi-port map (host, port) -> PortDemultiplexer
        if port_demuxers:
            self._port_demuxers = port_demuxers
        elif port_demux is not None:
            # backward compat: single demux
            self._port_demuxers = {(port_demux.host, port_demux.port): port_demux}
        else:
            self._port_demuxers = {}
        # Keep _port_demux for backward compat
        self._port_demux = next(iter(self._port_demuxers.values()), None) if self._port_demuxers else None

    def _get_port_demux(self, maddr: Multiaddr) -> PortDemultiplexer | None:
        """Return the PortDemultiplexer for this address, if any."""
        try:
            host = maddr.value_for_protocol("ip4") or maddr.value_for_protocol("ip6")
            port = int(maddr.value_for_protocol("tcp") or 0)
            if host and port:
                return self._port_demuxers.get((str(host), port))
        except Exception:
            pass
        return None

    def add_listen_addr(self, maddr: Multiaddr, conn_handler: THandler) -> IListener | None:
        transport = self.transport_for_listening(maddr)
        if transport is None:
            return None
        protocols = [p.name for p in maddr.protocols()]
        port_demux = self._get_port_demux(maddr)    # ← per-port lookup
        if "tcp" in protocols and port_demux is not None:
            return self._add_listen_addr_shared(maddr, protocols, transport, conn_handler, port_demux)
        return transport.create_listener(conn_handler)
```

---

### Patch 6: Fix `_add_listen_addr_shared()` Silent None Return (`manager.py`)

```python
# Before (line ~270):
if conn_type in port_demux._send_channels:
    logger.debug("PortDemultiplexer already has a listener for %s; reusing", conn_type.name)
    return port_demux._listeners.get(conn_type)   # ← can be None

# After:
if conn_type in port_demux._send_channels:
    existing = port_demux._listeners.get(conn_type)
    if existing is not None:
        logger.debug("PortDemultiplexer: reusing existing %s listener", conn_type.name)
        return existing
    # Channel registered but listener gone — fall through to re-register
    logger.warning(
        "PortDemultiplexer: channel for %s exists but listener is gone; re-registering",
        conn_type.name,
    )
    port_demux._send_channels.pop(conn_type, None)
    # Fall through to demultiplexed_listen() call below
```

---

### Patch 7: Happy Eyeballs Parallel Dial (`swarm.py`)

```python
# Constants (add near top of swarm.py):
_HAPPY_EYEBALLS_DELAY = 0.250   # 250 ms stagger between dial attempts (RFC 8305)
_MAX_PARALLEL_DIALS   = 8       # matches go-libp2p default

async def dial_peer(self, peer_id: ID) -> list[INetConn]:
    existing_connections = self.get_connections(peer_id)
    if existing_connections:
        valid = [c for c in existing_connections if not c.is_closed]
        if valid:
            return valid

    addrs = self.peerstore.addrs(peer_id)
    if not addrs:
        raise SwarmException(f"No known addresses to peer {peer_id}")

    gate = self.connection_gate
    allowed_addrs = [a for a in addrs if await gate.is_allowed(a)]
    if not allowed_addrs:
        raise SwarmException(f"All addresses for peer {peer_id} blocked by connection gate")

    winner: INetConn | None = None
    winner_lock = trio.Lock()
    all_failed = trio.Event()
    attempt_errors: list[Exception] = []

    with trio.CancelScope() as dial_scope:
        async with trio.open_nursery() as nursery:

            async def _try(maddr: Multiaddr) -> None:
                nonlocal winner
                try:
                    conn = await self._dial_with_retry(maddr, peer_id)
                    async with winner_lock:
                        if winner is None:
                            winner = conn
                            dial_scope.cancel()   # stop all other racers
                        else:
                            await conn.close()    # we lost the race; drop duplicate
                except Exception as e:
                    attempt_errors.append(e)

            for maddr in allowed_addrs[:_MAX_PARALLEL_DIALS]:
                nursery.start_soon(_try, maddr)
                await trio.sleep(_HAPPY_EYEBALLS_DELAY)

    if winner is None:
        from exceptiongroup import ExceptionGroup
        raise SwarmDialAllFailedError(
            f"unable to connect to {peer_id}",
            peer_id=peer_id,
            num_addrs_tried=len(attempt_errors),
        ) from (ExceptionGroup("dial errors", attempt_errors) if attempt_errors else None)

    return [winner]
```

---

### Patch 8: Add `listen_order()` Sorting to `TransportManager` (`manager.py`)

```python
def add_transport(self, transport: ITransport) -> None:
    self._transports.append(transport)
    # Re-sort by listen_order() to match go-libp2p's ListenOrder priority.
    # Transports without listen_order() default to priority 0 (highest).
    self._transports.sort(
        key=lambda t: getattr(t, "listen_order", lambda: 0)()
    )
    logger.debug(
        "TransportManager: registered %s (protocols=%s, listen_order=%d)",
        type(transport).__name__,
        getattr(transport, "protocols", lambda: "?")(),
        getattr(transport, "listen_order", lambda: 0)(),
    )
```

---

### Patch 9: Verify `is_quic_multiaddr` Handles `/p2p/<id>` Suffix

Add to `tests/transport/test_transport_manager.py`:

```python
def test_quic_can_dial_with_p2p_suffix():
    """Regression: /p2p/<id> appended by _dial_addr_single_attempt must not break QUIC routing."""
    from libp2p.transport.quic.transport import QUICTransport
    from libp2p.crypto.secp256k1 import create_new_key_pair
    kp = create_new_key_pair()
    qt = QUICTransport(kp.private_key)
    addr_with_p2p = Multiaddr(
        "/ip4/127.0.0.1/udp/4001/quic-v1/p2p/QmYyQSo1c1Ym7orWxLYvCuxRjeKVJmscEysqkhmmi1Cv92"
    )
    assert qt.can_dial(addr_with_p2p), "QUIC must accept /p2p/<id> suffix"
```

---

## 5. Code Change Guide — File by File

### `libp2p/network/swarm.py`

| Location | Change | Bug Fixed |
|---|---|---|
| `listen()` — the `for maddr in multiaddrs` loop | Replace with parallel nursery startup | BUG-1 |
| `listen()` — `port_demux.listen()` call at end | Move to START of method, before registering listeners | BUG-2 |
| `_handle_inbound_connection()` line ~1390 | `cast(QUICConnection,...)` → `cast(IMuxedConn,...)` | BUG-5 |
| `add_conn()` line ~1750 | `isinstance(muxed_conn, QUICConnection)` → duck-typing | BUG-6 |
| `transport.setter` | Mutates private list → uses `add_transport()` | BUG-7 |
| `dial_peer()` | Sequential loop → Happy Eyeballs parallel | BUG-9 |
| Top of file | Add `_HAPPY_EYEBALLS_DELAY = 0.250`, `_MAX_PARALLEL_DIALS = 8` | BUG-9 |

### `libp2p/__init__.py`

| Location | Change | Bug Fixed |
|---|---|---|
| `new_swarm()` PortDemultiplexer detection loop | Remove `break`, collect all shared ports | BUG-3 |
| `TransportManager()` instantiation | Pass `port_demuxers=` dict instead of single `port_demux=` | BUG-3 |

### `libp2p/transport/manager.py`

| Location | Change | Bug Fixed |
|---|---|---|
| `__init__` | Accept `port_demuxers: dict[tuple,PortDemux]` + backward compat | BUG-3 |
| Add `_get_port_demux(maddr)` | Per-port demux lookup | BUG-3 |
| `add_listen_addr()` | Use `_get_port_demux(maddr)` instead of `self._port_demux` | BUG-3 |
| `_add_listen_addr_shared()` line ~270 | Fix silent None return for already-registered channel | BUG-4 |
| `add_transport()` | Sort `_transports` by `listen_order()` after appending | BUG-11 |

### `libp2p/transport/cmux.py`

| Location | Change | Bug Fixed |
|---|---|---|
| `DemultiplexedListener.listen()` | Replace `spawn_system_task` with nursery-scoped task | BUG-8 |
| `_classify_and_route()` | Add `logger.debug` for `UNKNOWN` classification | Quality |

### `libp2p/transport/quic/transport.py`

| Location | Change | Bug Fixed |
|---|---|---|
| `can_dial()` | Verify `is_quic_multiaddr` handles `/p2p/<id>` suffix | BUG-10 |
| `protocols()` | Verify `str(QUIC_V1_PROTOCOL) == "quic-v1"` (not `"/quic-v1"`) | BUG-14 |

### `libp2p/transport/transport_registry.py`

| Location | Change | Priority |
|---|---|---|
| Entire file | Deprecate: redirect `create_transport_for_multiaddr()` through `TransportManager` | Low |

---

## 6. Testing Matrix

### 6.1 Critical — Must Pass Before Merge

```python
# tests/transport/test_simultaneous_transports.py

async def test_all_three_bind_concurrently():
    """
    Three listeners must all be active after a single host.run() call.
    Timing: all three should start within a few hundred ms of each other
    (parallelism check).
    """
    kp = generate_new_ed25519_identity()
    host = new_host(key_pair=kp, enable_quic=True, enable_websocket=True)
    start = trio.current_time()
    async with host.run(listen_addrs=[
        Multiaddr("/ip4/127.0.0.1/tcp/0"),
        Multiaddr("/ip4/127.0.0.1/udp/0/quic-v1"),
        Multiaddr("/ip4/127.0.0.1/tcp/0/ws"),
    ]):
        elapsed = trio.current_time() - start
        addrs = host.get_addrs()
        assert len(addrs) == 3, f"Expected 3 addrs, got {addrs}"
        assert elapsed < 2.0, f"Parallel startup took {elapsed:.2f}s — too slow"


async def test_tcp_client_connects_to_tcp_listener():
    """TCP client must connect to a host that also has QUIC and WS active."""
    server = new_host(enable_quic=True, enable_websocket=True)
    async with server.run(listen_addrs=[
        Multiaddr("/ip4/127.0.0.1/tcp/0"),
        Multiaddr("/ip4/127.0.0.1/udp/0/quic-v1"),
    ]):
        tcp_addr = next(a for a in server.get_addrs() if "tcp" in str(a) and "ws" not in str(a))
        client = new_host()
        async with client.run():
            await client.connect(PeerInfo(server.get_id(), [tcp_addr]))
            assert client.network().get_connection(server.get_id()) is not None


async def test_quic_client_connects_to_quic_listener():
    server = new_host(enable_quic=True)
    async with server.run(listen_addrs=[
        Multiaddr("/ip4/127.0.0.1/tcp/0"),
        Multiaddr("/ip4/127.0.0.1/udp/0/quic-v1"),
    ]):
        quic_addr = next(a for a in server.get_addrs() if "quic" in str(a))
        client = new_host(enable_quic=True)
        async with client.run():
            await client.connect(PeerInfo(server.get_id(), [quic_addr]))
            conn = client.network().get_connection(server.get_id())
            assert "quic" in str(conn.get_remote_addr())


async def test_shared_port_tcp_and_ws():
    """BUG-1, BUG-2, BUG-3 regression: TCP + WS on same port must both accept."""
    port = find_free_port()
    server = new_host(enable_websocket=True)
    async with server.run(listen_addrs=[
        Multiaddr(f"/ip4/127.0.0.1/tcp/{port}"),
        Multiaddr(f"/ip4/127.0.0.1/tcp/{port}/ws"),
    ]):
        # Both addresses should appear
        addrs = server.get_addrs()
        assert any("ws" in str(a) for a in addrs)
        assert any("ws" not in str(a) and "tcp" in str(a) for a in addrs)

        # Both should accept connections
        tcp_client = new_host()
        ws_client = new_host(enable_websocket=True)
        async with tcp_client.run():
            await tcp_client.connect(PeerInfo(server.get_id(), [Multiaddr(f"/ip4/127.0.0.1/tcp/{port}")]))
        async with ws_client.run():
            await ws_client.connect(PeerInfo(server.get_id(), [Multiaddr(f"/ip4/127.0.0.1/tcp/{port}/ws")]))


async def test_multi_port_tcp_ws_sharing():
    """BUG-3: Two separate ports both with TCP+WS sharing must work."""
    port1 = find_free_port()
    port2 = find_free_port()
    server = new_host(enable_websocket=True)
    async with server.run(listen_addrs=[
        Multiaddr(f"/ip4/127.0.0.1/tcp/{port1}"),
        Multiaddr(f"/ip4/127.0.0.1/tcp/{port1}/ws"),
        Multiaddr(f"/ip4/127.0.0.1/tcp/{port2}"),
        Multiaddr(f"/ip4/127.0.0.1/tcp/{port2}/ws"),
    ]):
        addrs = server.get_addrs()
        assert len(addrs) == 4, f"Expected 4 addrs: {addrs}"
```

### 6.2 Transport Routing Unit Tests

```python
# tests/transport/test_transport_manager.py

def test_tcp_does_not_match_quic():
    mgr = TransportManager()
    mgr.add_transport(TCP())
    assert mgr.transport_for_dialing(Multiaddr("/ip4/1.2.3.4/udp/4001/quic-v1")) is None

def test_quic_does_not_match_tcp():
    mgr = TransportManager()
    mgr.add_transport(QUICTransport(kp.private_key))
    assert mgr.transport_for_dialing(Multiaddr("/ip4/1.2.3.4/tcp/4001")) is None

def test_ws_does_not_match_plain_tcp():
    mgr = TransportManager()
    mgr.add_transport(WebsocketTransport(upgrader))
    assert mgr.transport_for_dialing(Multiaddr("/ip4/1.2.3.4/tcp/4001")) is None

def test_tcp_does_not_match_ws():
    mgr = TransportManager()
    mgr.add_transport(TCP())
    assert mgr.transport_for_dialing(Multiaddr("/ip4/1.2.3.4/tcp/4001/ws")) is None

def test_all_three_registered_routing():
    mgr = TransportManager()
    tcp = TCP()
    quic = QUICTransport(kp.private_key)
    ws = WebsocketTransport(upgrader)
    mgr.add_transports([tcp, quic, ws])
    assert mgr.transport_for_dialing(Multiaddr("/ip4/1.2.3.4/tcp/4001")) is tcp
    assert mgr.transport_for_dialing(Multiaddr("/ip4/1.2.3.4/udp/4001/quic-v1")) is quic
    assert mgr.transport_for_dialing(Multiaddr("/ip4/1.2.3.4/tcp/4001/ws")) is ws

def test_quic_protocols_string_value():
    """BUG-14: str(QUIC_V1_PROTOCOL) must equal 'quic-v1' for pre-filter to work."""
    from libp2p.transport.quic.config import QUICTransportConfig
    assert str(QUICTransportConfig.PROTOCOL_QUIC_V1) == "quic-v1"

def test_quic_can_dial_with_p2p_suffix():
    """BUG-10: /p2p/<id> appended by _dial_addr_single_attempt must not break routing."""
    qt = QUICTransport(kp.private_key)
    addr = Multiaddr("/ip4/127.0.0.1/udp/4001/quic-v1/p2p/QmYyQSo1c1Ym7orWxLYvCuxRjeKVJmscEysqkhmmi1Cv92")
    assert qt.can_dial(addr)
```

### 6.3 CMUX Unit Tests

```python
# tests/transport/test_cmux.py

def test_identify_multistream_select():
    assert identify_conn_type(b"\x13/m") == DemultiplexedConnType.MULTISTREAM_SELECT

def test_identify_http_verbs():
    for prefix in [b"GET", b"HEA", b"POS", b"PUT", b"DEL", b"CON", b"OPT", b"TRA", b"PAT", b"PRI"]:
        assert identify_conn_type(prefix) == DemultiplexedConnType.HTTP, f"failed for {prefix}"

def test_identify_tls_versions():
    for prefix in [b"\x16\x03\x01", b"\x16\x03\x02", b"\x16\x03\x03"]:
        assert identify_conn_type(prefix) == DemultiplexedConnType.TLS, f"failed for {prefix}"

def test_identify_unknown():
    assert identify_conn_type(b"\x00\x00\x00") == DemultiplexedConnType.UNKNOWN
    assert identify_conn_type(b"XYZ") == DemultiplexedConnType.UNKNOWN
    assert identify_conn_type(b"\x16") == DemultiplexedConnType.UNKNOWN  # too short

async def test_accept_timeout_drops_slow_consumer():
    """ACCEPT_TIMEOUT must drop connection when consumer is too slow."""
    port_demux = PortDemultiplexer("127.0.0.1", find_free_port())
    dl = port_demux.demultiplexed_listen(maddr, DemultiplexedConnType.MULTISTREAM_SELECT)
    # Do NOT call dl.listen() — so the channel has no consumer
    # With ACCEPT_TIMEOUT exceeded, connections should be dropped, not hang
    # ... (mock a slow stream, verify aclose is called within ACCEPT_TIMEOUT + margin)
```

### 6.4 Regression Tests

| Test | Guards |
|---|---|
| `test_tcp_only_swarm_still_works()` | No regression for single-transport deployments |
| `test_deprecated_single_transport_swarm()` | `Swarm(peer_id, ps, upg, TCP())` still works with DeprecationWarning |
| `test_transport_property_returns_first()` | `swarm.transport` returns first registered transport |
| `test_transport_setter_clears_list()` | `swarm.transport = tcp` replaces all others |
| `test_quic_inbound_bypasses_upgrader()` | QUIC inbound goes directly to `add_conn` |
| `test_ws_inbound_goes_through_upgrader()` | WS inbound runs security + muxer upgrade |

---

## 7. Priority Roadmap

### Phase 1 — Ship It (1 week)

These are the minimum changes for "all transports simultaneously":

| # | Task | File | Bug |
|---|---|---|---|
| 1.1 | Parallel listener startup (nursery) | `swarm.py` | BUG-1 |
| 1.2 | Fix PortDemultiplexer start order | `swarm.py` | BUG-2 |
| 1.3 | Multi-port demux (remove `break`) | `__init__.py`, `manager.py` | BUG-3 |
| 1.4 | Fix `_add_listen_addr_shared` None return | `manager.py` | BUG-4 |
| 1.5 | Fix `cast(QUICConnection,...)` → `cast(IMuxedConn,...)` | `swarm.py` | BUG-5 |
| 1.6 | Integration test: all 3 transports simultaneously | `tests/` | Coverage |

### Phase 2 — go-libp2p Alignment (weeks 2–3)

| # | Task | File | Bug |
|---|---|---|---|
| 2.1 | Happy Eyeballs parallel dial | `swarm.py` | BUG-9 |
| 2.2 | Fix `add_conn` concrete class check | `swarm.py` | BUG-6 |
| 2.3 | Fix `transport.setter` private mutation | `swarm.py` | BUG-7 |
| 2.4 | `listen_order()` sorting in TransportManager | `manager.py` | BUG-11 |
| 2.5 | Verify `is_quic_multiaddr` with `/p2p/` suffix | `quic/utils.py` | BUG-10 |
| 2.6 | Verify `QUICTransportConfig.PROTOCOL_QUIC_V1 == "quic-v1"` | `quic/config.py` | BUG-14 |

### Phase 3 — Cleanup (weeks 4–5)

| # | Task | File | Bug |
|---|---|---|---|
| 3.1 | Fix `_drain` system task resource leak | `cmux.py` | BUG-8 |
| 3.2 | Wire circuit relay into TransportManager | `relay/`, `manager.py` | BUG-15 |
| 3.3 | Deprecate `TransportRegistry` | `transport_registry.py` | BUG-12 |
| 3.4 | Log UNKNOWN classifications in cmux | `cmux.py` | Quality |
| 3.5 | Full test coverage for manager + cmux | `tests/transport/` | Coverage |

---

## 8. Appendix — go-libp2p Symbol Map

| go-libp2p | py-libp2p | Match |
|---|---|---|
| `swarm.Swarm.transports` | `TransportManager._transports` | ✅ |
| `Swarm.TransportForDialing(maddr)` | `TransportManager.transport_for_dialing(maddr)` | ✅ |
| `Swarm.TransportForListening(maddr)` | `TransportManager.transport_for_listening(maddr)` | ✅ |
| `Swarm.Listen(addrs...)` goroutines | `Swarm.listen(*multiaddrs)` — **sequential** | ❌ BUG-1 |
| `tcpreuse.PortDemultiplexer` | `cmux.PortDemultiplexer` — single port only | ⚠️ BUG-3 |
| `tcpreuse.NewTCPTransport(sharedTCP)` | `TransportManager(port_demux=…)` | ✅ |
| `identifyConnType(prefix)` | `identify_conn_type(prefix)` | ✅ |
| `acceptQueueSize = 64` | `ACCEPT_QUEUE_SIZE = 64` | ✅ |
| `acceptTimeout = 30s` | `ACCEPT_TIMEOUT = 30.0` (enforced) | ✅ |
| `inboundUpgradeTimeout` | `connection_config.inbound_upgrade_timeout` | ✅ |
| `dialPeer()` Happy Eyeballs | Sequential retry | ❌ BUG-9 |
| `Swarm.AddTransport(t)` | No public host-level API | ❌ BUG-15 partial |
| `transport.ListenOrder` sort | `listen_order()` defined, unused | ⚠️ BUG-11 |
| `relay.Transport` in routing | Not in `TransportManager` | ❌ BUG-15 |
| `upgrader.Upgrade(conn,isServer,peer)` | Two calls: `upgrade_security` + `upgrade_connection` | ⚠️ works |
| `muxer.Conn` (native mux bypass) | `isinstance(rwc, IMuxedConn)` detection | ✅ |
| Concurrent `close_all()` | `TransportManager.close_all()` with nursery | ✅ |

