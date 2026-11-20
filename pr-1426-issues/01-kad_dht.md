# Kademlia DHT Module — Spec Compliance, Robustness & Cleanup Issues

## Summary

The Kademlia DHT implementation (`libp2p/kad_dht/`) has multiple deviations from the IPFS DHT specification and libp2p Kademlia spec, plus correctness, robustness, and maintainability issues. These affect correctness, security, and interoperability with other libp2p implementations.

## Issues

### Critical

- **timeReceived uses wrong format**: The `timeReceived` field in records uses Unix epoch float instead of RFC3339Nano format per spec.
- **PUT_VALUE stream not reset on validation failure**: Per spec "On any error, the stream is reset." The stream is closed gracefully instead.
- **Record size not validated**: No maximum size check for PUT_VALUE records, allowing potential abuse.
- **Value store has no eviction limit**: No LRU eviction, risking OOM with large numbers of stored values.
- **Incoming timestamps can be forged**: `timeReceived` is accepted from remote records without being stripped.

### Spec Compliance

- **ADD_PROVIDER sender waits for an echo that never arrives**: Kubo does not respond to ADD_PROVIDER, so the send path blocks for the query timeout on every announcement.
- **ADD_PROVIDER key length not validated**: No 80-byte max enforcement per spec.
- **No ADD_PROVIDER rate limiting**: No per-peer rate limiting for ADD_PROVIDER messages.
- **No per-message provider cap**: ADD_PROVIDER messages can carry an unbounded number of provider records.
- **FIND_NODE key not validated**: Key is not validated as a valid multihash/PeerId.
- **GET_VALUE key size unlimited**: No max key size enforcement per spec.
- **GET_VALUE does not validate signatures**: Records are served without signature validation.
- **Closer peer addresses not stored**: GET_VALUE closer-peer addresses are not stored in the peerbook per spec.
- **Connection type always CONNECTED**: The connection type field always reports CONNECTED instead of dynamic reporting.

### Provider System

- **Provider lookup is single-shot**: `find_providers` only queries known providers, not using iterative lookup with closer peers.
- **No provider record republishing**: Provider records are not republished every 22 hours per spec.
- **No provider count limit**: No k=20 limit on providers per key.
- **CID validation missing**: No multihash structure checks for provider keys.
- **No persistence support**: No JSON save/load for the provider store.

### Value Store

- **No value record republishing**: Value records are not republished.
- **No persistence support**: No JSON save/load for the value store.

### Peer Routing

- **Lookup terminates too early**: Peer routing terminates when no new peers are discovered, even if unqueried closest peers remain.
- **No beta resiliency**: No BETA parameter ensuring closest peers are queried before termination.
- **No query timeout**: No total query timeout, risking infinite loops / hangs on unresponsive peers.
- **Failed peers not removed**: Peers that fail connection are not removed from the routing table.
- **Candidates not re-sorted**: Candidates are not re-sorted by distance after discovering closer peers.

### Security

- **No IP diversity filtering**: No limit on peers per subnet per bucket (eclipse-attack risk).
- **No max varint protection**: Varint-reading loops have no cap, risking DoS.
- **Server-mode not enforced**: Handlers registered regardless of mode.
- **No inbound concurrency limit**: Unbounded concurrent inbound DHT handlers.

### Bug Fixes

- **Hardcoded BUCKET_SIZE**: Value 20 hardcoded instead of using the constant.
- **PUT_VALUE does not reject on validator failure**: PUT_VALUE proceeds when `validator.select()` fails.
- **Routing table refresh uses wrong key**: Refresh does not use a random key within the bucket's XOR range.
- **DHT walk can hang**: The walk can discover the node's own ID from a remote peer and hang.
- **Wrong key encoding in provide/find_providers**: Keys are encoded with `key.encode()` instead of the raw CID multihash.
- **PUT_VALUE key comparison bug**: Validation compares the record key to itself instead of `message.key` vs `record.key`.
- **`cleanup_expired` crashes on empty store**: `UnboundLocalError` on an empty provider store.
- **get_value uses local routing table only**: Values at peers outside the local routing table are never found.
- **No cancel-on-quorum**: Outstanding value queries run to completion after quorum is reached.
- **IPNS records silently accepted**: The `ipns` namespace validator is never registered by default, so IPNS records are accepted without validation.
- **IPNS validator rejects base58 names**: `/ipns/<base58-peer-id>` keys (go-ipfs / py-ipfs-lite format) fail validation; only hex multihash is accepted.
- **ADD_PROVIDER sends stall on slow peers**: Lock-step batch sends wait for the slowest peer, blowing past the API budget.
- **Dead code present**: Unused helpers and constants (`_propagate_to_closest_peers`, `PEER_REFRESH_INTERVAL`, `_rt_refresh_nursery`, `should_republish()`, `PROVIDER_ADDRESS_TTL`, `gen_random_peer_id_with_cpl()`, `get_active_cpls()`, `_get_providers_from_peer()` wrapper, unused logging) remain in the module.

## Environment

- py-libp2p version: latest main branch
- Python version: 3.12+
- OS: macOS/Linux
