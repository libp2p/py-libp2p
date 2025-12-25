# Debugging the Interop Test

## Log File Locations

All logs are written to `/tmp/`:

1. **`/tmp/coordinator.log`** - Coordinator HTTP server logs

   - Shows when browser connects
   - Shows `/blpop` requests (browser getting listener address)
   - Shows `/results` requests (test results)

1. **`/tmp/python_listener.log`** - Python listener logs

   - Shows listener startup
   - Shows connection attempts
   - Shows ping requests received

1. **`/tmp/rust_dialer.log`** - Rust dialer logs

   - Shows compilation
   - Shows `[wasm_ping]` debug messages
   - Shows browser startup
   - Shows WASM loading

## Quick View Commands

```bash
# View all logs at once
cat /tmp/coordinator.log
cat /tmp/python_listener.log
cat /tmp/rust_dialer.log

# Follow logs in real-time (run in separate terminals)
tail -f /tmp/coordinator.log
tail -f /tmp/python_listener.log
tail -f /tmp/rust_dialer.log

# View last 50 lines of each
tail -50 /tmp/coordinator.log
tail -50 /tmp/python_listener.log
tail -50 /tmp/rust_dialer.log
```

## What to Look For

### Coordinator Log

- ✅ `POST /blpop HTTP/1.1" 200` - Browser successfully got listener address
- ✅ `Read listener address from file: /ip4/...` - Address was read correctly
- ❌ No `/blpop` requests - Browser didn't connect to coordinator
- ❌ No `/results` requests - Test didn't complete

### Python Listener Log

- ✅ `Listener ready, listening on:` - Listener started
- ✅ `received ping from ...` - Ping was received
- ❌ `Waiting for dialer to connect...` (no ping) - No connection made
- ❌ Connection errors - Network/address issues

### Rust Dialer Log

- ✅ `[wasm_ping] Browser navigated to WASM test page` - Browser loaded page
- ✅ `[wasm_ping] Page loaded, WASM should be executing...` - WASM should be running
- ❌ `[wasm_ping] Test timed out` - WASM didn't complete
- Look for `[wasm_ping]` messages to track execution flow

## Current Test Status

From your latest run:

- ✅ Coordinator received browser request and returned listener address
- ✅ Python listener is ready and waiting
- ✅ Rust dialer loaded WASM in browser
- ❌ **Issue**: Browser got the address but didn't connect to Python listener

## Debugging Steps

1. **Check if browser can reach Python listener:**

   ```bash
   # The listener address from logs
   # /ip4/192.168.1.17/tcp/45847/ws/p2p/...
   # Try to see if port is accessible
   netstat -tuln | grep 45847
   ```

1. **Check coordinator for errors:**

   ```bash
   grep -i error /tmp/coordinator.log
   ```

1. **Check Python listener for connection attempts:**

   ```bash
   grep -i "connect\|error\|exception" /tmp/python_listener.log
   ```

1. **Check Rust dialer for WASM errors:**

   ```bash
   grep -i "error\|fail\|exception" /tmp/rust_dialer.log
   ```

## Common Issues

1. **Browser can't reach listener** - Network/firewall issue
1. **Address format incompatible** - WASM expects different format
1. **WASM code error** - JavaScript error in browser (not visible in logs)
1. **Protocol mismatch** - Transport/security/muxer mismatch

## Next Steps

Since the browser successfully:

- Connected to coordinator
- Got the listener address
- Loaded WASM files

But didn't complete the ping, the issue is likely:

- WASM code failing silently (check browser console if possible)
- Network connectivity from browser to Python listener
- Address format incompatibility
