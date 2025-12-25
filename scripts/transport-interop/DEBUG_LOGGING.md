# Debug Logging Configuration

## Log File Locations

All debug logs are written to `/tmp/`:

1. **`/tmp/coordinator.log`** - Coordinator HTTP server (Python)
2. **`/tmp/python_listener.log`** - Python listener (Python)
3. **`/tmp/rust_dialer.log`** - Rust dialer (Rust)

## Debug Logging Status

### Python Components

✅ **Coordinator Server** - Debug logging enabled via `--debug` flag
- Location: Line 102 in `run_local_interop.sh`
- Logs: HTTP requests, CORS, address file reads

✅ **Python Listener** - Debug logging enabled via `--debug` flag
- Location: Line 119 in `run_local_interop.sh`
- Logs: Connection attempts, ping handling, libp2p internals

### Rust Component

✅ **Rust Dialer** - Debug logging enabled via `RUST_LOG=debug` environment variable
- Location: Line 178 in `run_local_interop.sh`
- Logs: WASM execution, browser interactions, libp2p internals

## Viewing Debug Logs

### View All Logs
```bash
# Coordinator
cat /tmp/coordinator.log

# Python Listener
cat /tmp/python_listener.log

# Rust Dialer
cat /tmp/rust_dialer.log
```

### Follow Logs in Real-Time
```bash
# In separate terminals:
tail -f /tmp/coordinator.log
tail -f /tmp/python_listener.log
tail -f /tmp/rust_dialer.log
```

### Filter for Errors
```bash
# Python errors
grep -i "error\|exception\|traceback" /tmp/python_listener.log
grep -i "error\|exception" /tmp/coordinator.log

# Rust errors
grep -i "error\|panic\|fail" /tmp/rust_dialer.log
```

### Filter for Specific Components
```bash
# Rust WASM ping messages
grep "\[wasm_ping\]" /tmp/rust_dialer.log

# Python listener events
grep -E "received ping|responded|connection|error" /tmp/python_listener.log

# Coordinator requests
grep -E "POST|GET|OPTIONS" /tmp/coordinator.log
```

## Debug Log Levels

### Python
- **INFO**: Normal operation messages
- **DEBUG**: Detailed internal state, connection details, protocol messages
- Set via `--debug` flag → `logging.DEBUG` level

### Rust
- **INFO**: Normal operation messages
- **DEBUG**: Detailed internal state, WASM execution, browser interactions
- Set via `RUST_LOG=debug` environment variable
- Also uses `tracing` crate for structured logging

## What to Look For

### Coordinator Log
- `POST /blpop` - Browser requesting listener address
- `Read listener address from file` - Address successfully read
- `POST /results` - Test results received
- CORS errors or connection issues

### Python Listener Log
- `Listener ready, listening on:` - Listener started
- `received ping from` - Ping received from dialer
- `responded with pong to` - Pong sent back
- Connection errors or protocol mismatches

### Rust Dialer Log
- `[wasm_ping] Starting...` - Dialer started
- `[wasm_ping] Browser navigated to WASM test page` - Browser loaded
- `[wasm_ping] Page loaded, WASM should be executing...` - WASM running
- `[wasm_ping] Test timed out` - Test didn't complete
- libp2p debug messages (connection, handshake, etc.)

## Troubleshooting

If debug logs are not appearing:

1. **Check if debug flags are set:**
   ```bash
   grep -n "debug\|RUST_LOG" run_local_interop.sh
   ```

2. **Check log file permissions:**
   ```bash
   ls -l /tmp/*.log
   ```

3. **Check if processes are writing:**
   ```bash
   # While test is running
   tail -f /tmp/coordinator.log
   tail -f /tmp/python_listener.log
   tail -f /tmp/rust_dialer.log
   ```

4. **Verify Python logging configuration:**
   - Check `configure_logging()` in `local_ping_listener.py`
   - Check `logging.basicConfig()` in `coordinator_server.py`

5. **Verify Rust logging configuration:**
   - Check `tracing_subscriber` setup in `wasm_ping.rs`
   - Check `RUST_LOG` environment variable is set

