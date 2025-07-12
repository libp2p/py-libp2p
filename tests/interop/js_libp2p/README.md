# py-libp2p and js-libp2p Interoperability Tests

This repository contains interoperability tests for py-libp2p and js-libp2p using the /ipfs/ping/1.0.0 protocol. The goal is to verify compatibility in stream multiplexing, protocol negotiation, ping handling, transport layer, and multiaddr parsing.

## Directory Structure

- js_node/ping.js: JavaScript implementation of a ping server and client using libp2p.
- py_node/ping.py: Python implementation of a ping server and client using py-libp2p.
- scripts/run_test.sh: Shell script to automate running the server and client for testing.
- README.md: This file.

## Prerequisites

- Python 3.8+ with `py-libp2p` and dependencies (`pip install libp2p trio cryptography multiaddr`).
- Node.js 16+ with `libp2p` dependencies (`npm install @libp2p/core @libp2p/tcp @chainsafe/libp2p-noise @chainsafe/libp2p-yamux @libp2p/ping @libp2p/identify @multiformats/multiaddr`).
- Bash shell for running `run_test.sh`.

## Running Tests

1. Change directory:

```
cd tests/interop/js_libp2p
```

2. Install dependencies:

```
For JavaScript: cd js_node && npm install && cd ...
```

3. Run the automated test:

For Linux and Mac users:

```
chmod +x scripts/run_test.sh
./scripts/run_test.sh
```

For Windows users:

```
.\scripts\run_test.ps1
```

This starts the Python server on port 8000 and runs the JavaScript client to send 5 pings.

## Debugging

- Logs are saved in py_node/py_server.log and js_node/js_client.log.
- Check for:
  - Successful connection establishment.
  - Protocol negotiation (/ipfs/ping/1.0.0).
  - 32-byte payload echo in server logs.
  - RTT and payload hex in client logs.

## Test Plan

### The test verifies:

- Stream Multiplexer Compatibility: Yamux is used and negotiates correctly.
- Multistream Protocol Negotiation: /ipfs/ping/1.0.0 is selected via multistream-select.
- Ping Protocol Handler: Handles 32-byte payloads per the libp2p ping spec.
- Transport Layer Support: TCP is used; WebSocket support is optional.
- Multiaddr Parsing: Correctly resolves multiaddr strings.
- Logging: Includes peer ID, RTT, and payload hex for debugging.

## Current Status

### Working:

- TCP transport and Noise encryption are functional.
- Yamux multiplexing is implemented in both nodes.
- Multiaddr parsing works correctly.
- Logging provides detailed debug information.

## Not Working:

- Ping protocol handler fails to complete pings (JS client reports "operation aborted").
- Potential issues with stream handling or protocol negotiation.
