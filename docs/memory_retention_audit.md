# Memory retention audit

This audit fixes reproduced ownership failures. It is not a certification that
all library code, optional transports, native dependencies, and arbitrary user
workloads are leak-free. RSS alone is not a leak test: intentional cache fill,
live connection state, and allocator retention must be distinguished from
objects that remain owned after their operation ends.

## Additional confirmed defects

| Owner                                                       | Failure                                                                                                   | Remediation and regression                                                                                                                              |
| ----------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| PubSub peer/subscription waiters and GossipSub mesh waiters | Timed-out or cancelled waits left events indexed indefinitely                                             | Remove an event when no tasks remain waiting; retain shared events for surviving callers. Exercise 1,000 timed-out waits and concurrent cancellation    |
| PeerData protocol book                                      | Repeated additions retained duplicate strings and list slots                                              | Deduplicate add/set operations, preserving first-seen order and in-place add behavior; 1,000 repeated updates retain two protocols                      |
| Fixed/sliding-window rate limiters                          | Entity histories lacked the token-bucket strategy's entity bound                                          | Apply the configured entity ceiling to every strategy; evict all state for the evicted least-recently-used entity; reject nonpositive tracking limits   |
| Resource-manager scope counters                             | Released and rolled-back counters kept zero-valued peer/service/protocol keys                             | Delete zero counters under the existing lock; preserve nonzero owners and cover all four limit-rejection stages                                         |
| QUIC per-connection diagnostic history                      | Retired CIDs and issued sequence histories grew for the connection's lifetime                             | Keep 128 recent history entries; cumulative issued/retired totals and live CID routing remain intact. Stress 5,000 rotations                            |
| QUIC registry sequence histogram                            | Diagnostics kept every lifetime sequence even after unregister                                            | Keep exact buckets 0–127 and aggregate other sequences into overflow bucket -1; routing retains full sequences. Stress 2,000 register/unregister cycles |
| Bitswap provider-discovery workers                          | A successful, failed, or cancelled fetch could leave its background lookup running until its old deadline | Give each fetch a private discovery cancel scope and cancel it when the fetch exits; test all three outcomes without waiting for wall-clock timeouts    |

The validation-cache overwrite stress test passed without a code change.
Provider/message caches, connection/peerstore bounds, and prior stream cleanup
regressions remain part of the existing coverage. This pass also runs the
related PubSub, QUIC CID, peerstore, resource-manager and Bitswap suites.

## Diagnostic compatibility

`get_connection_id_stats()['retired_connection_ids']` now counts recent retained
identities, capped at 128. `connection_ids_retired` remains the lifetime event
total. The sequence-distribution histogram has a documented overflow bucket
of -1, also exposed as `sequence_distribution_overflow_bucket`; exact routing
sequence numbers are unaffected.

## Validation policy

Reproduce teardown/timeout/cancellation failures in isolation first. Run targeted
and integration tests, then validate the immutable production image and deploy.
Use 10-second ownership/native-memory samples and rolling five-minute reports
for early feedback. Longer soaks run in the background and do not gate a fix.
A clean short run cannot exclude every slow leak.

## Follow-up: WebSocket close acknowledgement

Live ten-second samples exposed one closed WebSocket retained for more than
nine minutes. A focused regression reproduced a local-close deadlock: the
private host interpreted `WebSocketConnection.closed` as completed teardown,
but trio-websocket sets that property when sending the close frame. Cancelling
the reader then prevented the pending close acknowledgement from arriving.
The wrapper also had no internal close deadline, so its registry callback could
remain unreachable indefinitely.

Keep the reader alive until the wrapper finishes closing, and apply the
configured five-second close deadline to outbound and inbound wrappers. Tests
cover a delayed acknowledgement and an unresponsive peer using Trio's virtual
clock. Both failed before the change; both pass after it. This explains a
confirmed retained-owner path, not the entire live RSS slope.

## Follow-up: scoring and cancelled Bitswap requests

Repeated IP updates removed a peer from its old exact-IP set but left it in
all previous subnet sets. Disconnect removed only the current subnet. A
1,000-address churn regression now retains only another live peer's membership;
replacing an IP uses the complete existing IP/subnet removal path.

Bitswap `have_block()` registered its want and sent the initial probe before
entering `try/finally`. Failure or cancellation during that setup leaked the
want. Cleanup now covers setup as well as response waiting. Both outcomes are
reproduced using an immediate error or cancellation checkpoint.

Cancelling a global Bitswap want also left per-peer pending latency timestamps
behind (notably after interrupted batch requests, before their timeout path).
Cancel now forgets that CID's pending samples across peers, preserving other
CIDs and cumulative request/timeout totals. A 1,000-cancellation stress case
retains only an unrelated outstanding CID. These four regressions fail on
`b2d7e9f2` and pass after cleanup. Their production RSS contribution has not
been isolated; HAVE probes are not used by the normal py-ipfs-lite fetch path.

## Final active-path pass

GossipSub's health calculation returns early when no mesh topics exist, skipping
expiry of connection/disconnection history. Delivery timestamps were also
recorded even when adaptive health was disabled. Heartbeat maintenance now
expires both histories regardless of health mode and removes expired empty
per-topic delivery/publish entries. This matters for nodes running pubsub
without joining topics, including the production configuration.

Fanout expiry previously returned early when subscriber topic state vanished,
and removed fanout entries without their publish timestamps. Expiry now runs
before the subscriber check and releases both owners. DHT value deletion,
expiry and eviction now release local-key and republish metadata together;
a republish finishing after deletion cannot recreate its timestamp.

Nine additional regressions cover these cases, including 1,000-key churn and
retention of recent connection events. Reviewed Swarm dial/health/round-robin
cleanup, Noise cache call sites (not populated by the normal handshake path),
DHT provider bounds, pubsub rate-state expiry, existing transport teardown,
and Bitswap request ownership. User-owned published content, live streams,
connection buffers, bounded caches and optional/native transports remain
workload-dependent; this is not an exhaustive leak-free certification.
