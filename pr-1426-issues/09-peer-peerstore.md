# Peer & Peerstore — Memory-Leak, Growth & Hot-Path Performance Issues

## Summary

The peerstore (`libp2p/peer/`) leaks memory through `defaultdict` auto-creation, grows without bound, raises `KeyError` on uninitialized peer data, and has slow hot-path lookups: peer hashing encodes base58 on every call and `has_peer` materializes the full peer list.

## Issues

### Memory & Growth

- **`defaultdict` auto-creates entries**: Looking up an unknown peer creates an empty `PeerData` entry, leaking memory.
- **Unbounded growth**: No size limit on the peer-data map or `add_addrs`.
- **`KeyError` on uninitialized peer data**: `add_pubkey`, `add_privkey`, and metrics access entries that were never initialized.

### Performance

- **`ID.__hash__` computes base58 every call**: Peer-ID hashing (dict/set lookups, `peer_ids()` scans over tens of thousands of peers) is the dominant CPU cost on production nodes.
- **`has_peer` is O(n)**: Peer checks reconstruct and hash every peer in the store instead of an O(1) map lookup.

## Environment

- py-libp2p version: latest main branch
- Python version: 3.12+
- OS: macOS/Linux
