# py-libp2p and nim-libp2p Interoperability Tests

This directory contains interoperability tests for py-libp2p and nim-libp2p using the `/echo/1.0.0` protocol over QUIC transport. The goal is to verify compatibility in stream handling, protocol negotiation, QUIC transport, and message framing.

## Directory Structure

- `nim_echo_server.nim`: Nim implementation of an echo server using nim-libp2p.
- `test_echo_interop.py`: Python pytest tests that connect to the nim echo server.
- `conftest.py`: Pytest fixtures for managing the nim echo server lifecycle.
- `scripts`: Shell script to install dependencies and build the nim server.
- `README.md`: Contains details about running the tests.

## Prerequisites

### Python

- Python 3.8+

- Install required dependencies:

```bash
pip install -e .
```

### Nim

- Nim 2.0+ (required by nim-libp2p)
- Nimble (Nim package manager)

Install Nim (if not already installed):

```bash
# Using choosenim (recommended)
curl https://nim-lang.org/choosenim/init.sh -sSf | sh

# Or via package manager
# Ubuntu/Debian
apt install nim

# macOS
brew install nim
```

Verify Nim installation:

```bash
nim --version
nimble --version
```

## Running Tests

### 1. Navigate to the test directory

```bash
cd tests/interop/nim_libp2p
```

### 2. Build the nim echo server

Run the setup script to install nim-libp2p and build the echo server binary:

```bash
chmod +x scripts/setup_nim_echo.sh
./scripts/setup_nim_echo.sh
```

This script will:

- Check if Nim is available
- Install nim-libp2p globally (if not already installed)
- Compile `nim_echo_server.nim` with QUIC support
- Output the binary as `nim_echo_server`

### 3. Run the tests

Run all interop tests using pytest:

```bash
pytest -v -s
```

Or run specific tests:

```bash
# Basic echo test
pytest -v -s test_echo_interop.py::test_basic_echo_interop

# Large message echo test
pytest -v -s test_echo_interop.py::test_large_message_echo
```

To see logger output in terminal (shows `logger.info()` messages):

```bash
pytest -v -s --log-cli-level=INFO
```

### 4. Run tests directly (alternative)

You can also run the tests directly:

```bash
python test_echo_interop.py
```

## Test Plan

### The tests verify:

- **QUIC Transport Compatibility**: QUIC-v1 transport works between py-libp2p and nim-libp2p.
- **Multistream Protocol Negotiation**: `/echo/1.0.0` is selected via multistream-select.
- **Echo Protocol Handler**: Messages are echoed back correctly with varint length-prefix framing.
- **Unicode Support**: UTF-8 encoded messages (including special characters) are handled correctly.
- **Large Messages**: Messages up to 5KB are processed without issues.

### Test Cases

1. **Basic Echo Test** (`test_basic_echo_interop`):

   - Sends multiple text messages including Unicode characters
   - Verifies each message is echoed back correctly

1. **Large Message Test** (`test_large_message_echo`):

   - Sends larger payloads (1KB and 5KB)
   - Verifies large message handling works correctly

## Current Status

### Working:

- QUIC transport with nim-libp2p
- Echo protocol implementation
- Varint length-prefixed message framing
- Unicode message support
- Automated server lifecycle management in tests
