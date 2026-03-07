# Per-Peer Outbound RPC Queue — Go ↔ Python Reference

This document maps every feature of **go-libp2p-pubsub**'s outbound RPC
queue / splitting / sending pipeline to its corresponding implementation in
**py-libp2p**, with line-level references to both codebases.

> **Go reference**: [`github.com/libp2p/go-libp2p-pubsub`](https://github.com/libp2p/go-libp2p-pubsub) (master)

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Constants](#2-constants)
3. [Priority Queue](#3-priority-queue)
4. [RPC Queue (Async Wrapper)](#4-rpc-queue-async-wrapper)
5. [Peer Lifecycle (Create / Destroy Queue)](#5-peer-lifecycle-create--destroy-queue)
6. [Per-Peer Sending Loop](#6-per-peer-sending-loop)
7. [Enqueue Path — GossipSub](#7-enqueue-path--gossipsub)
8. [Enqueue Path — FloodSub](#8-enqueue-path--floodsub)
9. [Drop-RPC Handling](#9-drop-rpc-handling)
10. [RPC Splitting (the `split` / `split_rpc` method)](#10-rpc-splitting)
11. [Control-Message Coalescing Details](#11-control-message-coalescing-details)
12. [Test Coverage](#12-test-coverage)
13. [Differences & Notes](#13-differences--notes)

---

## 1. Architecture Overview

Both Go and Python follow the same architecture for outbound message sending:

```
Producer (gossipsub / floodsub)
        │
        ▼
  ┌────────────────────┐
  │    RPC Queue        │  bounded, two-tier priority
  │  (per peer)         │
  └────────┬───────────┘
           │  async pop
           ▼
  ┌────────────────────┐
  │  split_rpc()       │  break large RPCs into ≤ max_message_size chunks
  └────────┬───────────┘
           │
           ▼
  ┌────────────────────┐
  │  write_msg()       │  varint-prefixed write to the libp2p stream
  └────────────────────┘
```

| Concept | Go file | Python file |
|---------|---------|-------------|
| Priority queue | `rpc_queue.go` | `rpc_queue.py` — `PriorityQueue` |
| Async queue wrapper | `rpc_queue.go` (`rpcQueue`) | `rpc_queue.py` — `RpcQueue` |
| RPC splitting | `gossipsub.go` (`GossipSubRouter.split`) | `rpc_queue.py` — `RpcQueue.split_rpc()` |
| Sending loop | `comm.go` (`handleSendingMessages`) | `pubsub.py` — `Pubsub.handle_sending_messages()` |
| Queue creation | `comm.go` (`handleNewPeer`) | `pubsub.py` — `Pubsub._handle_new_peer()` |
| Queue teardown | `pubsub.go` (`handleDeadPeers`) | `pubsub.py` — `Pubsub._handle_dead_peer()` |
| Enqueue (gossipsub) | `gossipsub.go` (`doSendRPC`) | `gossipsub.py` — `GossipSub.send_rpc()` |
| Drop handler | `gossipsub.go` (`doDropRPC`) | `gossipsub.py` — `GossipSub.drop_rpc()` |

---

## 2. Constants

| Constant | Go | Python | Notes |
|----------|-----|--------|-------|
| `DefaultMaxMessageSize` | `1 << 20` (1 MiB) — `pubsub.go` | `1 * 1024 * 1024` — `rpc_queue.py:27` | Identical |
| `peerOutboundQueueSize` / `OutBoundQueueSize` | `32` — `pubsub.go` | `32` — `rpc_queue.py:31` | Identical |

---

## 3. Priority Queue

### Go — `priorityQueue` (`rpc_queue.go`)

```go
type priorityQueue struct {
    urgent []*RPC   // control messages
    others []*RPC   // data messages
    max    int
}
```

- **Push**: `urgent` or `others` slice. Returns `ErrQueueFull` when `len(urgent) + len(others) >= max`.
- **Pop**: Drains `urgent` first, then `others` (FIFO within each tier).

### Python — `PriorityQueue` (`rpc_queue.py:35-93`)

```python
class PriorityQueue:
    _priority: deque[rpc_pb2.RPC]      # ← Go's "urgent"
    _non_priority: deque[rpc_pb2.RPC]  # ← Go's "others"
    max_size: int                       # default = OutBoundQueueSize (32)
```

| Feature | Go | Python |
|---------|-----|--------|
| Push when full | Returns `ErrQueueFull` | Returns `False` |
| Pop order | `urgent` first, then `others` | `_priority` first, then `_non_priority` |
| Data structure | Go slices (pop from front) | `collections.deque` (O(1) `popleft`) |
| Default capacity | 32 | 32 |

---

## 4. RPC Queue (Async Wrapper)

### Go — `rpcQueue` (`rpc_queue.go`)

```go
type rpcQueue struct {
    pq      priorityQueue
    cond    sync.Cond    // blocks reader
    closed  bool
}
// Push / UrgentPush / Pop / Close
```

- `Push` / `UrgentPush` wake blocked consumer via `cond.Broadcast()`.
- `Pop` blocks on `cond.Wait()` until items arrive or queue is closed.

### Python — `RpcQueue` (`rpc_queue.py:96-173`)

```python
class RpcQueue:
    _queue: PriorityQueue
    _notify: trio.Event     # ← replaces sync.Cond
    _closed: bool
```

| Feature | Go | Python |
|---------|-----|--------|
| Wake mechanism | `sync.Cond.Broadcast()` | `trio.Event.set()` (re-created each push) |
| Block mechanism | `sync.Cond.Wait()` | `await trio.Event.wait()` |
| Push return | `error` (`ErrQueueFull`) | `bool` (`False` = full or closed) |
| Pop on close | Returns `nil` | Returns `None` |

---

## 5. Peer Lifecycle (Create / Destroy Queue)

### Queue creation

**Go** — `comm.go` → `handleNewPeer`:
```go
q := newRpcQueue(peerOutboundQueueSize)
peer.sendQueue = q
go gs.handleSendingMessages(ctx, peer, q)
```

**Python** — `pubsub.py:744-748` → `_handle_new_peer`:
```python
queue = RpcQueue()
self.peer_queues[peer_id] = queue
self.manager.run_task(self.handle_sending_messages, peer_id, stream, queue)
```

Both create a per-peer queue and spawn a dedicated sending loop goroutine / trio task.

### Queue teardown

**Go** — `pubsub.go` → `handleDeadPeers`:
```go
peer.sendQueue.Close()
```

**Python** — `pubsub.py:772-773` → `_handle_dead_peer`:
```python
if peer_id in self.peer_queues:
    self.peer_queues.pop(peer_id).close()
```

`close()` sets the closed flag and wakes the consumer so it exits its loop.

---

## 6. Per-Peer Sending Loop

### Go — `comm.go` → `handleSendingMessages`

```go
func (p *PubSub) handleSendingMessages(ctx context.Context, s *Stream, outgoing *rpcQueue) {
    for {
        rpc := outgoing.Pop(ctx)
        if rpc == nil { return }
        err := p.writeRpc(rpc, s)
        ...
    }
}
```

- Pops from queue, calls `writeRpc` which serialises + varint-prefixes.

### Python — `pubsub.py:822-845` → `handle_sending_messages`

```python
async def handle_sending_messages(self, peer_id, stream, queue):
    while True:
        rpc = await queue.pop()
        if rpc is None:
            return
        ok = await self.write_msg(stream, rpc)
        if not ok:
            return
```

- Pops from queue and writes directly — splitting has already been done at
  enqueue time (matching Go).

---

## 7. Enqueue Path — GossipSub

### Go — `gossipsub.go` → `doSendRPC` / `doDropRPC`

```go
func (gs *GossipSubRouter) doSendRPC(rpc *RPC, p peer.ID, q *rpcQueue) {
    err := q.Push(rpc, false)   // or UrgentPush for control
    if err != nil {
        gs.doDropRPC(rpc, p)
    }
}
```

- `sendRPC` piggybacks control messages, splits if oversized, then calls `doSendRPC`.
- Control-only RPCs use `UrgentPush` (priority).
- If the queue is full, `doDropRPC` logs the drop and saves GRAFT/PRUNE for retry.

### Python — `gossipsub.py:1556-1580` → `send_rpc`

```python
def send_rpc(self, peer_id, rpc, priority=False):
    queue = self.pubsub.peer_queues.get(peer_id)
    if queue is None:
        return
    for part in queue.split_rpc(rpc):
        ok = queue.push(part, priority=priority)
        if not ok:
            self.drop_rpc(peer_id, part)
```

`send_rpc` splits the RPC first, then pushes each chunk individually — matching
Go's `sendRPC` → `split` → `doSendRPC`-per-chunk pattern.  Each chunk is
attempted independently; a single drop does not abort the remaining chunks.

Three call sites in GossipSub were converted from direct `write_msg` to `send_rpc`:

| Call site | Method | Priority |
|-----------|--------|----------|
| Publish to mesh peers | `publish()` | `False` |
| IWANT response (requested messages) | `handle_iwant()` | `False` |
| All control messages (GRAFT, PRUNE, IHAVE, IWANT, IDONTWANT) | `emit_control_message()` | `True` |

---

## 8. Enqueue Path — FloodSub

### Python — `floodsub.py:149-158` → `publish`

```python
for peer_id in peers_gen:
    queue = pubsub.peer_queues.get(peer_id)
    if queue is not None:
        for part in queue.split_rpc(rpc_msg):
            ok = queue.push(part)
            if not ok:
                logger.debug("floodsub: queue full for peer %s, dropping RPC", peer_id)
                break
```

FloodSub splits at enqueue time (matching the Go pattern), then pushes each
chunk.  If the queue fills up mid-split, remaining chunks are dropped and the
loop moves to the next peer.

---

## 9. Drop-RPC Handling

### Go — `gossipsub.go` → `doDropRPC`

```go
func (gs *GossipSubRouter) doDropRPC(rpc *RPC, p peer.ID) {
    log.Debugf("dropping message to peer %s: queue full", p)
    // Save GRAFT/PRUNE control for retry via pushControl
    ...
}
```

### Python — `gossipsub.py:1582-1591` → `drop_rpc`

```python
def drop_rpc(self, peer_id, rpc):
    logger.debug(
        "Dropping outbound RPC for peer %s (publish=%d, control=%s)",
        peer_id, len(rpc.publish), rpc.HasField("control"),
    )
```

Currently a logging stub. Go additionally calls `pushControl` to save
GRAFT/PRUNE for the next heartbeat — this is a future enhancement for Python.

---

## 10. RPC Splitting

This is the most complex piece. Both Go and Python split at **enqueue time**.
Go does it inside `GossipSubRouter.split` (an `iter.Seq[RPC]` generator).
Python does it in `RpcQueue.split_rpc()`, called from `send_rpc()` /
`publish()` before pushing chunks onto the queue.

### Go — `gossipsub.go` → `GossipSubRouter.split`

```go
func (gs *GossipSubRouter) split(rpc *RPC) iter.Seq[RPC] {
    return func(yield func(RPC)bool) {
        // 1. Publish messages
        // 2. Subscriptions
        // 3. Control: IHave (coalesced by topicID)
        // 4. Control: IWant (coalesced into single ControlIWant)
        // 5. Control: Graft
        // 6. Control: Prune
        // 7. Control: IDontWant
        // Flush remaining
    }
}
```

### Python — `rpc_queue.py:180-366` → `RpcQueue.split_rpc`

```python
def split_rpc(self, rpc: rpc_pb2.RPC) -> list[rpc_pb2.RPC]:
    # 1. Publish messages
    # 2. Subscriptions
    # 3. Control: IHave (coalesced by topicID)
    # 4. Control: IWant (coalesced into single ControlIWant)
    # 5. Control: Graft
    # 6. Control: Prune
    # 7. Control: IDontWant
    # Flush remaining
```

### Splitting strategy per section

Every section follows the same pattern: iterate items, append to the *current*
output RPC, and when `current.ByteSize()` would exceed `max_message_size`,
flush `current` to the output list and start a new RPC.

| Section | Go behaviour | Python behaviour | Alignment |
|---------|-------------|-----------------|-----------|
| **Publish** | Iterate `rpc.Publish`, append `Message` until over limit, flush. Oversized single message emitted alone. | Same. `rpc_queue.py:213-226` | ✅ Identical |
| **Subscriptions** | Iterate `rpc.Subscriptions`, same flush logic. | Same. `rpc_queue.py:228-238` | ✅ Identical |
| **IHave** | Coalesced by `topicID` — reuses last `ControlIHave` if topicID matches, else starts new entry. Message IDs added one at a time; when over limit, flush + start fresh IHave with same topicID. | Same. `rpc_queue.py:244-289` | ✅ Identical |
| **IWant** | All `ControlIWant` entries merged into a **single** `ControlIWant`. Message IDs added one at a time; when over limit, flush + start fresh IWant. | Same. `rpc_queue.py:291-318` | ✅ Identical |
| **Graft** | Each `ControlGraft` appended; when over limit, flush. | Same. `rpc_queue.py:320-331` | ✅ Identical |
| **Prune** | Each `ControlPrune` appended; when over limit, flush. | Same. `rpc_queue.py:333-344` | ✅ Identical |
| **IDontWant** | Each `ControlIDontWant` appended; oversized single entry has its `messageIDs` split across RPCs. | Same. `rpc_queue.py:346-364` | ✅ Identical |
| **Flush** | `yield` remaining buffer if non-empty. | Append remaining to output list. Return `[RPC()]` if nothing was produced. | ✅ Equivalent |

---

## 11. Control-Message Coalescing Details

### IHave — coalesce by topicID

Go's `appendOrMergeRPC` and `split` both group IHave entries by topic:

```go
// Go pseudocode (split):
if len(out.Control.Ihave) == 0 || out.Control.Ihave[last].TopicID != ihave.TopicID {
    out.Control.Ihave = append(out.Control.Ihave, &pb.ControlIHave{TopicID: ihave.TopicID})
}
out.Control.Ihave[last].MessageIDs = append(..., mid)
```

Python equivalent (`rpc_queue.py:253-267`):

```python
ihave_list = current.control.ihave
if len(ihave_list) == 0 or ihave_list[-1].topicID != ihave.topicID:
    new_ihave = rpc_pb2.ControlIHave(topicID=ihave.topicID)
    ihave_list.append(new_ihave)
    ...
for mid in ihave.messageIDs:
    last_ihave = current.control.ihave[-1]
    last_ihave.messageIDs.append(mid)
```

### IWant — coalesce into single entry

Go merges all IWant message IDs into one `ControlIWant`:

```go
// Go pseudocode (split):
if len(out.Control.Iwant) == 0 {
    out.Control.Iwant = append(out.Control.Iwant, &pb.ControlIWant{})
}
out.Control.Iwant[0].MessageIDs = append(..., mid)
```

Python equivalent (`rpc_queue.py:295-305`):

```python
if len(current.control.iwant) == 0:
    new_iwant = rpc_pb2.ControlIWant()
    current.control.iwant.append(new_iwant)
    ...
for mid in iwant.messageIDs:
    current.control.iwant[0].messageIDs.append(mid)
```

---

## 12. Test Coverage

All tests live in `tests/core/pubsub/test_rpc_queue.py` (39 tests) plus
integration test updates across 3 files.

### Unit tests — `test_rpc_queue.py`

| Class | # | What it covers |
|-------|---|----------------|
| **TestPriorityQueue** | 8 | Deque types, `len`, push/pop non-priority, push/pop priority, priority-first pop order, reject when full (both tiers), default max_size |
| **TestRpcQueue** | 7 | Close flag, push return values, `len`, async pop, pop blocks until push (trio), pop returns `None` on close, FIFO ordering |
| **TestSplitRpc** | 14 | Empty RPC, small (no split), publish split, oversized single publish, subscriptions split, IHave split, IHave final batch not lost, IWant no double-append, IWant split oversized, Graft split, Prune split, mixed content preserved, IDontWant split, IDontWant small |
| **TestSizeOfEmbeddedMsg** | 2 | Small message, empty message |
| **TestVarintSize** | 3 | Zero, small (1-byte), two-byte, three-byte |
| **TestConstants** | 2 | `DefaultMaxMessageSize == 1 MiB`, `OutBoundQueueSize == 32` |

### Key regression tests

| Test | Regression it guards against |
|------|------------------------------|
| `test_oversized_single_publish_emitted_alone` | Infinite loop when a single message exceeds `max_message_size` |
| `test_ihave_final_batch_not_lost` | Last IHave batch silently dropped (off-by-one in flush) |
| `test_iwant_no_double_append` | IWant IDs duplicated when both break-path and post-loop path fire |
| `test_push_rejected_when_full` | Old code dropped the *oldest* item; now correctly rejects the *new* item |
| `test_priority_popped_before_non_priority` | Old code popped non-priority first; now priority drains first |

### Integration test updates

| File | Change |
|------|--------|
| `tests/core/pubsub/test_gossipsub.py` | `test_handle_iwant`, `test_handle_iwant_invalid_msg_id` — mock `send_rpc` instead of `write_msg` |
| `tests/core/pubsub/test_gossipsub_v1_1_ihave_iwant.py` | `test_iwant_retrieves_missing_messages` — `send_rpc_mock` |
| `tests/core/pubsub/test_gossipsub_v1_1_score_gates.py` | Added `MagicMock` import; `mock_send_rpc` for synchronous `send_rpc` |

---

## 13. Differences & Notes

| Topic | Go | Python | Rationale |
|-------|-----|--------|-----------|
| **Split timing** | At enqueue (`sendRPC` → `split` → `doSendRPC` per chunk) | At enqueue (`send_rpc` / `publish` → `split_rpc` → `push` per chunk) | Identical — both split before pushing onto the per-peer queue. |
| **Iterator vs list** | `split` returns `iter.Seq[RPC]` (lazy generator) | `split_rpc` returns `list[rpc_pb2.RPC]` (eager) | Python protobuf objects aren't zero-copy; materialising the list is simpler and safe since each chunk is small. |
| **GRAFT/PRUNE retry** | `doDropRPC` calls `pushControl` to save control messages for the next heartbeat | `drop_rpc` only logs | Future enhancement — no data-path correctness impact since control messages are priority and rarely dropped. |
| **Sync primitives** | `sync.Cond` + `sync.Mutex` | `trio.Event` (re-created per push) | trio's structured concurrency model doesn't support `Cond`; `Event` provides equivalent wake semantics. |
| **Protobuf field types** | `[]byte` for message IDs | Protobuf auto-converts `bytes` → `str` | Test assertions use string comparisons (`"only-one"` not `b"only-one"`) to match protobuf behaviour. |

---

## File Reference

| File | Lines changed | Purpose |
|------|---------------|---------|
| `libp2p/pubsub/rpc_queue.py` | **NEW** (390 lines) | Priority queue, RPC queue, split_rpc, constants |
| `libp2p/pubsub/pubsub.py` | +40 lines | Queue lifecycle + sending loop |
| `libp2p/pubsub/gossipsub.py` | +32/−25 lines | `send_rpc` / `drop_rpc` + 3 call-site conversions |
| `libp2p/pubsub/floodsub.py` | +5/−2 lines | Publish via `peer_queues` |
| `tests/core/pubsub/test_rpc_queue.py` | **NEW** (~435 lines) | 39 unit tests |
| `tests/core/pubsub/test_gossipsub.py` | mock updates | `send_rpc` mock |
| `tests/core/pubsub/test_gossipsub_v1_1_ihave_iwant.py` | mock updates | `send_rpc` mock |
| `tests/core/pubsub/test_gossipsub_v1_1_score_gates.py` | mock + import | `MagicMock` for sync `send_rpc` |
