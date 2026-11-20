# Network & Swarm Module — Dial Pipeline, Auto-Connector & Connection Management Issues

## Summary

The network layer (`libp2p/network/`) has issues in the dial pipeline, the auto-connector, and connection management: the dial pipeline is not aligned with go-libp2p, the auto-connector causes CPU bursts and wasted dials at scale, connection registration can be lost to dial deadlines, and the API surface is missing O(1) peer checks and notifee removal.

## Issues

### Dial Pipeline

- **Dial pipeline not aligned with go-libp2p**: No dial batching, no `MaxConcurrentDials` cap, no transport ranking.
- **Inbound connection cap not atomic**: The inbound connection cap is not enforced atomically, allowing races.
- **Connection registration lost to dial deadline**: Connection registration can be cancelled by the dial deadline, decaying connected peers to 0.
- **Inbound security-upgrade failures logged at ERROR**: Expected failures flood the error log.

### Auto-Connector

- **Always tops up to high water**: The auto-connector aims for the high-water mark instead of the midpoint of `[low_water, high_water]`.
- **CPU bursts at scale**: Dial bursts when scaling to 300+ peers cause CPU spikes.
- **Wasted dials**: Dials are wasted on relay addresses, IPv6, and QUIC-first candidates.
- **Private-only candidates dialed on public nodes**: Peers with only private addresses are dialed by public nodes.
- **Concurrent auto_connect tasks / dial storms**: Disconnect events can spawn concurrent auto-connect tasks and dial storms.
- **Unbounded tracking caches**: AutoConnector tracking caches grow without pruning.

### Stream / Connection Layer

- **`net_stream` lacks `is_closed`**: No way for leak-reconciliation consumers to check stream closure.
- **`INetwork` lacks `remove_notifee`**: Notifees cannot be unregistered.
- **`IPeerStore` lacks O(1) `has_peer`**: Peer checks materialize the full peer list.
- **Dead code present**: Dead `notify_all` in the swarm.

## Environment

- py-libp2p version: latest main branch
- Python version: 3.12+
- OS: macOS/Linux
