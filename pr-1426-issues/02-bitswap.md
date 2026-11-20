# Bitswap Module — Stream Management, Memory & Performance Issues

## Summary

The Bitswap implementation (`libp2p/bitswap/`) has architectural and performance issues: it dials a new stream per message instead of reusing persistent streams, has no message batching, suffers from O(n) memory growth on large file transfers, and contains dead code.

## Issues

### Architecture

- **No persistent stream reuse**: A new stream is dialed per message instead of maintaining one persistent outbound stream per peer (Kubo/go-bitswap architecture).
- **No message batching**: Wantlists, cancels, block presences, and data blocks are not coalesced into debounced write frames; every update triggers a separate send.
- **No automatic stream reconnection**: Streams are not transparently re-established on errors, causing per-message dialing overhead.

### Performance

- **O(n) memory growth on large transfers**: `leaf_triples` retains `block_bytes` for every leaf after the block is stored, so peak memory scales ~8x file size (e.g. ~16 GB for a 2 GB file).
- **Wasted dials for DontHave responses**: Outbound dial-back streams are dialed for `DontHave` responses.

### Logging / Cleanup

- **Noisy wantlist logging**: Per-wantlist-entry traces are logged at WARNING level.
- **Dead code present**: Unused DecisionEngine code remains in the module.

## Environment

- py-libp2p version: latest main branch
- Python version: 3.12+
- OS: macOS/Linux
