#!/bin/bash
# Test the Rust dialer in isolation to verify it works

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_RUST_DIR="$SCRIPT_DIR/rust-local"
COORDINATOR_PORT=8080

echo "Testing Rust dialer in isolation..."
echo "This will:"
echo "1. Start coordinator server"
echo "2. Start a dummy listener (or use existing one)"
echo "3. Run Rust dialer with debug output"
echo ""

# Check if coordinator is already running
if ! curl -s "http://localhost:$COORDINATOR_PORT/results" > /dev/null 2>&1; then
    echo "Starting coordinator server..."
    cd "$SCRIPT_DIR"
    python3 coordinator_server.py --port $COORDINATOR_PORT > /tmp/test_coordinator.log 2>&1 &
    COORD_PID=$!
    sleep 2
    echo "Coordinator started (PID: $COORD_PID)"
else
    echo "Coordinator already running"
    COORD_PID=""
fi

# Set up WASM package
if [ -f "$LOCAL_RUST_DIR/build.sh" ]; then
    echo "Setting up WASM package..."
    "$LOCAL_RUST_DIR/build.sh"
fi

# Set environment variables
export transport=ws
export security=noise
export muxer=mplex
export ip=0.0.0.0
export is_dialer=true
export test_timeout_seconds=30
export redis_addr="127.0.0.1:$COORDINATOR_PORT"

# Write a dummy listener address for testing
echo "/ip4/127.0.0.1/tcp/8000/ws/p2p/12D3KooWTest1234567890123456789012345678901234567890123456789" > /tmp/libp2p_listener_addr.txt
echo "Dummy listener address written to /tmp/libp2p_listener_addr.txt"

echo ""
echo "Running Rust dialer with full debug output..."
echo "Environment:"
echo "  transport=$transport"
echo "  security=$security"
echo "  muxer=$muxer"
echo "  redis_addr=$redis_addr"
echo ""

cd "$LOCAL_RUST_DIR"
RUST_LOG=debug cargo run --bin wasm_ping 2>&1 | tee /tmp/rust_dialer_test.log

echo ""
echo "Test complete. Check /tmp/rust_dialer_test.log for full output."

# Cleanup
if [ -n "$COORD_PID" ]; then
    kill $COORD_PID 2>/dev/null || true
fi
