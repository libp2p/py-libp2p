# Local Transport Interop Test

This directory contains a local version of the transport interop test plan that runs without Docker or Redis. It focuses on testing interoperability between **chromium-rust-v0.53** and **python-v0.4** using **WebSocket (ws), Noise security, and mplex multiplexer**.

## Overview

The test orchestrates a ping transport test between:
- **Python listener** (py-libp2p v0.4): Listens for incoming connections
- **Rust chromium dialer** (rust-libp2p v0.53): Runs in a browser and dials the Python listener

The test measures:
- `handshakePlusOneRTTMillis`: Time from connection start to first ping response
- `pingRTTMilllis`: Round-trip time for a single ping

## Prerequisites

1. **Python 3.11+** with py-libp2p installed
2. **Rust** with cargo installed
3. **chromedriver** compatible with your Chrome/Chromium version
4. **Rust libp2p interop-tests** checked out at:
   ```
   $HOME/PNL_Launchpad_Curriculum/Libp2p/rust-libp2p/interop-tests
   ```
   Or set `RUST_PROJECT_ROOT` environment variable to point to your rust-libp2p root directory.
5. **wasm-pack** and **rustup** (for building WASM package)

## Setup

### 1. Build Rust WASM Package

The WASM package needs to be built from the rust-libp2p interop-tests project. The script will attempt to build it automatically, but you can build manually:

```bash
cd $HOME/PNL_Launchpad_Curriculum/Libp2p/rust-libp2p/interop-tests
source $HOME/.cargo/env  # If using rustup
/tmp/wasm-pack build --target web  # Or use system wasm-pack if installed
```

This creates the `pkg/` directory with the compiled WASM module.

### 2. Install Python Dependencies

```bash
pip install aiohttp
```

Or if using venv:
```bash
source venv/bin/activate
pip install aiohttp
```

## Running the Test

Simply run the orchestration script:

```bash
cd /home/luca/Informatica/Learning/PNL_Launchpad_Curriculum/Libp2p/py-libp2p/scripts/transport-interop
./run_local_interop.sh
```

The script will:
1. Start a coordination HTTP server (replaces Redis)
2. Start the Python listener (ws, noise, mplex)
3. Start the Rust chromium dialer in a browser
4. Wait for the test to complete
5. Display the results

### Environment Variables

You can customize the test by setting environment variables:

```bash
# Point to your rust-libp2p directory (if different from default)
export RUST_PROJECT_ROOT=/path/to/rust-libp2p

# Run the test
./run_local_interop.sh
```

## Log Files

All log files are written to `/tmp/`:

- **`/tmp/coordinator.log`** - Coordinator HTTP server logs
- **`/tmp/python_listener.log`** - Python listener logs (includes debug output)
- **`/tmp/rust_dialer.log`** - Rust dialer (wasm_ping) logs
- **`/tmp/interop_test_result.json`** - Test results (if test completes successfully)

To view logs:
```bash
# View all logs
tail -f /tmp/coordinator.log
tail -f /tmp/python_listener.log
tail -f /tmp/rust_dialer.log

# View test results
cat /tmp/interop_test_result.json | python3 -m json.tool
```

## Components

### `run_local_interop.sh`
Main orchestration script that:
- Checks prerequisites
- Builds WASM package if needed
- Starts all components
- Monitors test execution
- Displays results

### `local_ping_listener.py`
Python listener that:
- Listens on WebSocket transport
- Uses Noise security
- Uses mplex multiplexer
- Writes its address to a file for coordination
- Handles ping requests

### `coordinator_server.py`
Simple HTTP server that:
- Provides `/blpop` endpoint (Redis proxy for Rust wasm)
- Provides `/results` endpoint to receive test results
- Reads listener address from file
- Serves results via HTTP

### `rust-local/`
Local Rust project that:
- Compiles independently (avoids dependency issues)
- Serves WASM package to browser
- Runs chromedriver and browser
- Uses HTTP coordinator instead of Redis

## Test Configuration

The test is configured for:
- **Transport**: WebSocket (`ws`)
- **Security**: Noise
- **Multiplexer**: mplex
- **Test timeout**: 30 seconds (configurable in script)

## Output

On success, the script outputs JSON results:

```json
{
  "handshakePlusOneRTTMillis": 15.2,
  "pingRTTMilllis": 2.1
}
```

## Troubleshooting

### chromedriver not found
Install chromedriver compatible with your Chrome version:
- Download from: https://chromedriver.chromium.org/
- Or use package manager: `pacman -S chromium` (Arch Linux)

### WASM package not built
The script will attempt to build it automatically, but you can build manually:
```bash
cd $RUST_PROJECT_ROOT/interop-tests
source $HOME/.cargo/env
/tmp/wasm-pack build --target web
```

### Port conflicts
The script uses:
- Port 8080 for coordinator server
- Port 8081 for WASM server (Rust dialer)
- Random port for chromedriver (auto-selected)
- Auto-selected port for Python listener

If port 8080 is in use, modify `COORDINATOR_PORT` in `run_local_interop.sh`.

### Test timeout
If the test times out, check logs:
- `/tmp/python_listener.log` - Python listener logs
- `/tmp/rust_dialer.log` - Rust dialer logs
- `/tmp/coordinator.log` - Coordinator server logs

Common issues:
- WASM package not built or missing files
- Browser not starting (check chromedriver)
- Network connectivity issues between browser and listener

### Viewing logs in real-time
```bash
# Terminal 1: Watch coordinator
tail -f /tmp/coordinator.log

# Terminal 2: Watch Python listener
tail -f /tmp/python_listener.log

# Terminal 3: Watch Rust dialer
tail -f /tmp/rust_dialer.log

# Terminal 4: Run test
./run_local_interop.sh
```

## Manual Testing

You can also run components manually:

### Start Coordinator Server
```bash
python3 coordinator_server.py --port 8080
```

### Start Python Listener
```bash
python3 local_ping_listener.py --transport ws --address-file /tmp/libp2p_listener_addr.txt
```

### Run Rust Dialer
```bash
cd $RUST_PROJECT_ROOT/interop-tests
export transport=ws
export security=noise
export muxer=mplex
export ip=0.0.0.0
export is_dialer=true
export test_timeout_seconds=30
export redis_addr=127.0.0.1:8080
cargo run --bin wasm_ping
```

## Differences from Original Test Plan

This local version:
- ✅ No Docker containers
- ✅ No Redis dependency (uses file + HTTP coordination)
- ✅ Focused on single test: chromium-rust-v0.53 x python-v0.4 (ws, noise, mplex)
- ✅ Runs entirely on localhost
- ✅ Simpler setup and debugging
- ✅ Uses local Rust project to avoid compilation issues

The original test plan supports multiple implementations and configurations, while this version focuses on the specific combination needed for local development and testing.
