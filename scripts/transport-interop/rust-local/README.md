# Local Rust WASM Ping Test

This is a local, standalone version of the Rust `wasm_ping` binary that can compile independently of the main rust-libp2p project. It avoids the compilation issues in the main project by using updated dependencies.

## Overview

This local Rust project:
- Compiles independently with fixed dependencies
- Uses the WASM package from the main rust-libp2p project (via symlink)
- Provides the same functionality as the main project's `wasm_ping` binary
- Works with the local interop test orchestration script

## Building

The project will automatically set up WASM package symlinks when you run the main test script. To build manually:

```bash
cd /home/luca/Informatica/Learning/PNL_Launchpad_Curriculum/Libp2p/py-libp2p/scripts/transport-interop/rust-local
./build.sh  # Sets up WASM package symlinks
cargo build --bin wasm_ping
```

## Requirements

1. The WASM package must be built in the main rust-libp2p project:
   ```bash
   cd $HOME/PNL_Launchpad_Curriculum/Libp2p/rust-libp2p/interop-tests
   wasm-pack build --target web
   ```

2. If the main project has compilation issues, you may need to:
   - Fix dependency issues in the main project, OR
   - Use a pre-built WASM package from another source

## Differences from Main Project

- Uses updated dependencies that compile with Rust 1.92+
- Doesn't include the full libp2p library (only serves WASM)
- Uses HTTP proxy for coordination instead of direct Redis
- Simpler structure focused on serving the WASM test

## Usage

The local Rust project is automatically used by `run_local_interop.sh` if it exists. You can also run it manually:

```bash
export transport=ws
export security=noise
export muxer=mplex
export ip=0.0.0.0
export is_dialer=true
export test_timeout_seconds=300
export redis_addr=127.0.0.1:8080

cd /home/luca/Informatica/Learning/PNL_Launchpad_Curriculum/Libp2p/py-libp2p/scripts/transport-interop/rust-local
cargo run --bin wasm_ping
```


