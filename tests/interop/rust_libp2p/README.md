# libp2p Interoperability Tests

This directory contains interoperability tests between py-libp2p and rust-libp2p implementations, focusing on the ping protocol to verify core compatibility.

## Overview

The tests verify the following libp2p components work correctly between implementations:

- **Transport Layer**: TCP connection establishment
- **Security Layer**: Noise encryption protocol
- **Stream Multiplexing**: Yamux multiplexer compatibility  
- **Protocol Negotiation**: Multistream-select protocol selection
- **Application Protocol**: Ping protocol (`/ipfs/ping/1.0.0`)

## Test Structure

```
├── py_node/
│   └── ping.py          # Python libp2p ping client/server
├── rust_node/
│   ├── src/main.rs      # Rust libp2p ping client/server
│   └── Cargo.toml
└── scripts/
    ├── run_py_to_rust_test.ps1   # Test: Python client → Rust server
    └── run_rust_to_py_test.ps1   # Test: Rust client → Python server
```

## Prerequisites

### Python Environment
```bash
# Install py-libp2p and dependencies
pip install .
```

### Rust Environment
```bash
# Ensure Rust is installed
rustc --version
cargo --version

# Dependencies are defined in rust_node/Cargo.toml
```

## Running Tests

### Test 1: Rust Client → Python Server

This test starts a Python server and connects with a Rust client:

```powershell
# Run the automated test
.\scripts\run_rust_to_py_test.ps1

# Or with custom parameters
.\scripts\run_rust_to_py_test.ps1 -Port 9000 -PingCount 10
```

**Manual steps:**
1. Start Python server: `python py_node/ping.py server --port 8000`
2. Note the Peer ID from server output
3. Run Rust client: `cargo run --manifest-path rust_node/Cargo.toml -- /ip4/127.0.0.1/tcp/8000/p2p/<PEER_ID>`

### Test 2: Python Client → Rust Server

This test starts a Rust server and connects with a Python client:

```powershell
# Run the automated test (requires manual intervention)
.\scripts\run_py_to_rust_test.ps1

# Follow the on-screen instructions to complete the test
```

**Manual steps:**
1. Start Rust server: `cargo run --manifest-path rust_node/Cargo.toml`
2. Note the Peer ID and port from server output
3. Run Python client: `python py_node/ping.py client /ip4/127.0.0.1/tcp/<PORT>/p2p/<PEER_ID> --count 5`

## Expected Behavior

### Successful Test Output

**Python Server Logs:**
```
[INFO] Starting py-libp2p ping server...
[INFO] Peer ID: QmYourPeerIdHere
[INFO] Listening: /ip4/0.0.0.0/tcp/8000
[INFO] New ping stream opened by 12D3KooW...
[PING 1] Received ping from 12D3KooW...: 32 bytes
[PING 1] Echoed ping back to 12D3KooW...
```

**Rust Client Logs:**
```
Local peer ID: 12D3KooW...
Listening on "/ip4/0.0.0.0/tcp/54321"
Dialed /ip4/127.0.0.1/tcp/8000/p2p/QmYourPeerIdHere
Behaviour(Event { peer: QmYourPeerIdHere, result: Ok(Pong) })
```

### Performance Metrics

The tests measure:
- **Connection Establishment Time**: Time to establish secure connection
- **Round-Trip Time (RTT)**: Latency for ping/pong exchanges
- **Success Rate**: Percentage of successful ping attempts
- **Protocol Negotiation**: Successful selection of `/ipfs/ping/1.0.0`

## Troubleshooting

### Common Issues

1. **Protocol Mismatch**: Ensure both implementations use the same protocol ID
   - Python: `/ipfs/ping/1.0.0`
   - Rust: `/ipfs/ping/1.0.0` (default ping protocol)

2. **Connection Timeout**: 
   - Check firewall settings
   - Verify correct IP addresses and ports
   - Ensure both peers are running

3. **Noise Encryption Errors**:
   - Verify cryptography library versions
   - Check that both implementations support the same Noise variants

4. **Yamux Multiplexing Issues**:
   - Confirm Yamux protocol versions match
   - Check stream handling implementation

### Debug Logging

Enable detailed logging:

**Python:**
```bash
# Logs are automatically written to ping_debug.log
tail -f ping_debug.log
```

**Rust:**
```bash
# Set environment variable for detailed logs
$env:RUST_LOG="debug"
cargo run --manifest-path rust_node/Cargo.toml
```

## Interoperability Checklist

- [ ] TCP transport connection establishment
- [ ] Noise encryption handshake
- [ ] Yamux stream multiplexing
- [ ] Multistream protocol negotiation
- [ ] Ping protocol payload exchange (32 bytes)
- [ ] Proper connection cleanup
- [ ] Error handling and timeouts
- [ ] Performance metrics collection

## Contributing

When adding new tests:

1. Follow the existing pattern for client/server implementations
2. Add appropriate error handling and logging
3. Update this README with new test procedures
4. Ensure tests clean up resources properly
