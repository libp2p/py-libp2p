# py-libp2p and rust-libp2p Interoperability Tests

This directory contains interoperability tests between py-libp2p and rust-libp2p using the `/ipfs/ping/1.0.0` protocol over TCP transport. The goal is to verify compatibility in connection handling, protocol negotiation, and ping/pong message exchange.

## Directory Structure

- `rust_node/`: Rust implementation of a ping server using rust-libp2p.
  - `src/main.rs`: Main Rust ping server source code.
  - `Cargo.toml`: Rust dependencies and project configuration.
- `test_ping_interop.py`: Python pytest tests that connect to the Rust ping server.
- `conftest.py`: Pytest fixtures for building and managing the Rust server lifecycle.
- `README.md`: Contains details about running the tests.

## Prerequisites

### Python

- Python 3.8+

- Install required dependencies:

```bash
pip install -e .
```

### Rust

- Rust 1.75+ (with Cargo)

Install Rust (if not already installed):

```bash
# Using rustup (recommended)
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
```

Verify Rust installation:

```bash
rustc --version
cargo --version
```

## Running Tests

### 1. Navigate to the test directory

```bash
cd tests/interop/rust_libp2p
```

### 2. Build the Rust ping server

Build the Rust binary manually:

```bash
cd rust_node
cargo build --release
cd ..
```

> **Note:** The pytest fixtures will automatically build the binary if it doesn't exist and Cargo is available. You can skip this step if you prefer automatic building.

### 3. Run the tests

Run all interop tests using pytest:

```bash
pytest -v -s
```

To see logger output in terminal:

```bash
pytest -v -s --log-cli-level=INFO
```

### 4. Run tests directly (alternative)

You can also run the tests directly:

```bash
python test_ping_interop.py
```

## Test Plan

### The tests verify:

- **TCP Transport Compatibility**: TCP transport works between py-libp2p and rust-libp2p.
- **Multistream Protocol Negotiation**: `/ipfs/ping/1.0.0` is selected via multistream-select.
- **Ping Protocol Handler**: Ping requests are handled correctly and RTT values are returned.
- **Connection Establishment**: Python node can successfully dial and connect to a Rust node.

### Test Cases

1. **Ping Interop Test** (`test_ping_interop`):
   - Starts a Rust ping server
   - Python node connects to the Rust server over TCP
   - Sends 5 ping requests
   - Verifies RTT values are returned and are positive

## Current Status

### Working:

- TCP transport with rust-libp2p
- Ping protocol implementation
- Automated server lifecycle management in tests
- Auto-build of Rust binary via pytest fixtures
