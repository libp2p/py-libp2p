# WebRTC Interoperability Tests

This directory contains interoperability tests for WebRTC transport across different libp2p implementations (Python, Go, Rust, and JavaScript).

## Overview

The tests verify that the py-libp2p WebRTC implementation can successfully establish connections and exchange data with:

- Go libp2p
- Rust libp2p
- JavaScript libp2p
- Python libp2p

## Prerequisites

### Python Dependencies

Install Python dependencies including WebRTC support:

```bash
pip install -e ".[webrtc]"
```

### Redis Server

The tests use Redis for coordination between peers. Start a Redis server:

```bash
# Using Docker
docker run -d -p 6379:6379 redis:latest

# Or install locally
# On Ubuntu/Debian
sudo apt-get install redis-server
sudo systemctl start redis

# On macOS
brew install redis
brew services start redis

# On Windows
# Download from https://redis.io/download or use WSL
```

### Other Language Implementations

To run the full interop tests, you'll need:

#### Go

```bash
# Install Go (1.19+)
# Then install dependencies
cd tests/interop/webrtc
go mod download
```

#### Rust

```bash
# Install Rust (1.70+)
# Then build
cd tests/interop/webrtc
cargo build --release
```

#### JavaScript

```bash
# Install Node.js (18+)
# Then install dependencies
cd tests/interop/webrtc
npm install
```

## File Structure

```
tests/interop/webrtc/
├── README.md              # This file
├── requirements.txt       # Python dependencies
├── py_peer.py            # Python peer (listener/dialer using libp2p)
├── py_listener.py        # Python WebRTC listener (aiortc)
├── py_dialer.py          # Python WebRTC dialer (aiortc)
├── test_runner.py        # Test orchestration
├── run_all_tests.sh      # Shell script to run all tests
├── go_peer.go            # Go libp2p peer
├── go.mod                # Go dependencies
├── go.sum                # Go dependency checksums
├── rs_peer.rs            # Rust libp2p peer
├── src/main.rs           # Rust main entry point
├── Cargo.toml            # Rust dependencies
├── Cargo.lock            # Rust dependency lock
├── js_peer.js            # JavaScript libp2p peer
├── package.json          # Node.js dependencies
└── package-lock.json     # Node.js dependency lock
```

## Running Tests

### Quick Start

Run all interoperability tests:

```bash
cd tests/interop/webrtc
./run_all_tests.sh
```

### Individual Tests

#### Python-to-Python (libp2p)

```bash
# Terminal 1: Start listener
python py_peer.py --role listener --port 9090

# Terminal 2: Start dialer
python py_peer.py --role dialer
```

#### Python-to-Python (aiortc WebRTC)

```bash
# Terminal 1: Start listener
python py_listener.py

# Terminal 2: Start dialer
python py_dialer.py
```

#### Python-to-Go

```bash
# Terminal 1: Start Go listener
go run go_peer.go listener

# Terminal 2: Start Python dialer
python py_peer.py --role dialer
```

#### Python-to-Rust

```bash
# Terminal 1: Start Rust listener
cargo run --release -- listener

# Terminal 2: Start Python dialer
python py_peer.py --role dialer
```

#### Python-to-JavaScript

```bash
# Terminal 1: Start JS listener
node js_peer.js listener

# Terminal 2: Start Python dialer
python py_peer.py --role dialer
```

### Using the Test Runner

The test runner automates the process:

```bash
python test_runner.py
```

This will:

1. Check that Redis is running
1. Start listener peers for each implementation
1. Start dialer peers to connect to listeners
1. Verify connections and ping/pong exchanges
1. Report results
