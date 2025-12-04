# QUIC-Related Tests in go-libp2p and quinn

This document lists all QUIC-related tests found in go-libp2p and quinn (Rust QUIC library) for reference.

## go-libp2p QUIC Tests

### `p2p/transport/quic/` - Core QUIC Transport Tests

#### `conn_test.go` - Connection Tests

- `TestHandshake` - Tests QUIC handshake with different configurations
- `TestResourceManagerSuccess` - Tests resource manager allowing connections
- `TestResourceManagerDialDenied` - Tests resource manager denying dial connections
- `TestResourceManagerAcceptDenied` - Tests resource manager denying accept connections
- `TestStreams` - Tests stream creation and handling
- `testStreamsErrorCode` - Tests stream error codes
- `TestHandshakeFailPeerIDMismatch` - Tests handshake failure on peer ID mismatch
- `TestConnectionGating` - Tests connection gating functionality
- `TestDialTwo` - Tests dialing two connections
- `TestStatelessReset` - Tests stateless reset functionality
- `TestHolePunching` - Tests hole punching functionality

#### `listener_test.go` - Listener Tests

- `TestListenAddr` - Tests listening on IPv4 and IPv6 addresses
- `TestAccepting` - Tests accepting connections
- `TestAcceptAfterClose` - Tests accept behavior after listener close
- `TestCorrectNumberOfVirtualListeners` - Tests virtual listener count
- `TestCleanupConnWhenBlocked` - Tests connection cleanup when blocked

#### `transport_test.go` - Transport Tests

- `TestQUICProtocol` - Tests QUIC protocol support
- `TestCanDial` - Tests dial capability checks

#### `cmd/lib/lib_test.go` - Command Library Tests

- `TestCmd` - Tests command functionality

### `p2p/transport/quicreuse/` - QUIC Connection Reuse Tests

#### `connmgr_test.go` - Connection Manager Tests

- `TestListenOnSameProto` - Tests listening on same protocol
- `TestConnectionPassedToQUICForListening` - Tests connection passed to QUIC for listening
- `TestAcceptErrorGetCleanedUp` - Tests cleanup of accept errors
- `TestConnectionPassedToQUICForDialing` - Tests connection passed to QUIC for dialing
- `TestListener` - Tests listener functionality
- `TestExternalTransport` - Tests external transport integration
- `TestAssociate` - Tests connection association
- `TestConnContext` - Tests connection context
- `TestAssociationCleanup` - Tests association cleanup
- `TestConnManagerIsolation` - Tests connection manager isolation

#### `reuse_test.go` - Reuse Tests

- `TestReuseListenOnAllIPv4` - Tests reuse listening on all IPv4
- `TestReuseListenOnAllIPv6` - Tests reuse listening on all IPv6
- `TestReuseCreateNewGlobalConnOnDial` - Tests creating new global connection on dial
- `TestReuseConnectionWhenDialing` - Tests connection reuse when dialing
- `TestReuseConnectionWhenListening` - Tests connection reuse when listening
- `TestReuseConnectionWhenDialBeforeListen` - Tests connection reuse when dialing before listening
- `TestReuseListenOnSpecificInterface` - Tests reuse listening on specific interface
- `TestReuseGarbageCollect` - Tests garbage collection of reused connections

#### `quic_multiaddr_test.go` - Multiaddr Conversion Tests

- `TestConvertToQuicMultiaddr` - Tests converting to QUIC multiaddr
- `TestConvertToQuicV1Multiaddr` - Tests converting to QUIC v1 multiaddr
- `TestConvertFromQuicV1Multiaddr` - Tests converting from QUIC v1 multiaddr

### `p2p/test/quic/` - Integration Tests

- `TestQUICAndWebTransport` - Tests QUIC and WebTransport integration

## quinn (Rust QUIC Library) Tests

### `quinn/src/tests.rs` - Core QUIC Tests

#### Connection Tests

- `handshake_timeout` - Tests handshake timeout behavior
- `close_endpoint` - Tests endpoint closing
- `local_addr` - Tests local address retrieval
- `read_after_close` - Tests reading after connection close
- `export_keying_material` - Tests keying material export
- `ip_blocking` - Tests IP blocking functionality

#### Stream Tests

- `zero_rtt` - Tests zero-RTT connection establishment
- `echo_v6` - Tests echo functionality over IPv6
- `echo_v4` - Tests echo functionality over IPv4
- `echo_dualstack` - Tests echo functionality with dual stack
- `stress_receive_window` - Stress test for receive window (50 streams, 25KB each)
- `stress_stream_receive_window` - Stress test for stream receive window (2 streams, 250KB each)
- `stress_both_windows` - Stress test for both windows (50 streams, 25KB each)

#### Advanced Tests

- `rebind_recv` - Tests rebinding receive socket
- `stream_id_flow_control` - Tests stream ID flow control
- `two_datagram_readers` - Tests two datagram readers
- `multiple_conns_with_zero_length_cids` - Tests multiple connections with zero-length connection IDs
- `stream_stopped` - Tests stream stopped functionality
- `stream_stopped_2` - Additional stream stopped test

### `quinn/tests/many_connections.rs` - Many Connections Test

- `connect_n_nodes_to_1_and_send_1mb_data` - Tests connecting 50 nodes to 1 server and sending 1MB data each

### `quinn/tests/post_quantum.rs` - Post-Quantum Cryptography Tests

- Tests for post-quantum cryptography support (specific test names not extracted)

## Key Observations

### go-libp2p

- **No negotiation semaphore**: go-libp2p QUIC transport does not use a negotiation semaphore
- **Resource manager integration**: Extensive tests for resource manager integration
- **Connection reuse**: Dedicated tests for connection reuse functionality
- **Stream handling**: Tests for stream creation, error codes, and cleanup
- **No stress tests**: No high-concurrency stream stress tests found (unlike py-libp2p's `test_yamux_stress_ping`)

### quinn

- **Pure QUIC library**: Not libp2p-specific, focuses on QUIC protocol implementation
- **Stream limits**: Uses `max_concurrent_bidi_streams` and `max_concurrent_uni_streams` for flow control
- **Stress tests**: Includes stress tests with multiple streams (50 streams in some tests)
- **No negotiation semaphore**: No negotiation semaphore (not applicable to pure QUIC)
- **Flow control focus**: Tests focus on QUIC flow control and window management

## Comparison with py-libp2p

### Similarities

- Both test connection establishment and handshake
- Both test stream creation and handling
- Both test error handling and cleanup

### Differences

- **py-libp2p**: Has negotiation semaphore for multiselect protocol negotiation
- **go-libp2p**: No negotiation semaphore (handles protocol negotiation differently)
- **quinn**: No negotiation semaphore (pure QUIC, not libp2p)
- **py-libp2p**: Has `test_yamux_stress_ping` with 100 concurrent streams
- **go-libp2p**: No equivalent high-concurrency stress test found
- **quinn**: Has stress tests but with lower concurrency (50 streams max)

## Notes for py-libp2p Development

1. **Negotiation semaphore is py-libp2p-specific**: Neither go-libp2p nor quinn use a negotiation semaphore, suggesting this is a py-libp2p architectural decision to handle multiselect protocol negotiation.

1. **Stress test uniqueness**: py-libp2p's `test_yamux_stress_ping` with 100 concurrent streams is more aggressive than tests found in go-libp2p or quinn.

1. **Semaphore limit tuning**: Since other implementations don't use negotiation semaphores, the optimal limit for py-libp2p may need to be determined empirically based on:

   - Server processing capacity
   - Event loop performance
   - Resource constraints
   - Test environment (CI/CD vs local)

1. **Potential optimization**: Consider investigating how go-libp2p handles high-concurrency protocol negotiation without a semaphore, as it may provide insights for py-libp2p optimization.
