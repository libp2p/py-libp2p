# Resource Manager / Connection Manager — Connection-Lifecycle Issues

## Summary

The connection manager (`libp2p/rcmgr/`) has multiple bugs in connection lifecycle management: connection limits are not enforced, pruning is unsafe or synchronous, disconnected peers are re-dialed, notifee failures tear down connections, and the lifecycle manager is not wired into the swarm.

## Issues

### Enforcement

- **`max_connections` not enforced on outbound dials**: Outbound dials bypass the connection cap.
- **`max_connections` race at registration**: Registration-time enforcement is racy.
- **`min_connections` non-functional**: The minimum-connections setting has no effect.
- **Lifecycle manager not wired into the swarm**: Connection limits are never actually enforced.
- **`dial_peer` results uncapped**: Results are not capped at `max_connections_per_peer`.

### Connection Handling

- **`add_conn` dedup closes the shared muxed connection**: Duplicate registration closes a connection other code still uses.
- **Per-peer connection trimming is unsafe**: Trimming can disrupt in-use connections.
- **Connection getters return live internals**: Callers can mutate internal state through getter results.
- **Pruner allow-list checks the wrong IP**: The allow-list does not use the connection's real remote IP.
- **`Swarm.close()` is non-deterministic**: Active connections are not closed deterministically.

### Pruning & Reconnection

- **Pruning runs synchronously**: Connection pruning has no debounce and blocks the caller.
- **No auto-connect on disconnect**: The node does not immediately replenish dropped connections.
- **Recently-disconnected peers re-dialed**: No back-off from re-dialing peers that just disconnected.
- **Negative-peer-cache TTL too long**: Rejected peers are cached too long and there is no eviction API.

### Robustness

- **Notifee failures tear down connections**: A failing notifee can bring down healthy connections.
- **Lifecycle tracker ratchet wedges node at 0 peers**: The tracker can ratchet such that the node never reconnects.
- **`add_conn` failures not logged**: Failures/closers are silent.
- **`has_peer` is O(n)**: Peer lookup materializes the full peer list.
- **Dead code present**: The connection pool is dead code (off by default).

## Environment

- py-libp2p version: latest main branch
- Python version: 3.12+
- OS: macOS/Linux
