#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYPROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$SCRIPT_DIR"

PASSED=0
FAILED=0
TOTAL=0

pass_test() {
    echo "  ✅ PASS: $1"
    PASSED=$((PASSED + 1))
    TOTAL=$((TOTAL + 1))
}

fail_test() {
    echo "  ❌ FAIL: $1"
    FAILED=$((FAILED + 1))
    TOTAL=$((TOTAL + 1))
}

# Cleanup on exit
PIDS=()
export IPFS_PATH=$(mktemp -d)
cleanup() {
    for pid in "${PIDS[@]+"${PIDS[@]}"}"; do
        kill "$pid" 2>/dev/null || true
        wait "$pid" 2>/dev/null || true
    done
    rm -rf "$IPFS_PATH"
}
trap cleanup EXIT

wait_ready_and_parse() {
    local pid=$1
    local outfile=$2
    local prefix=$3
    local timeout=30
    local elapsed=0
    while [ $elapsed -lt $timeout ]; do
        if grep -q "^$prefix" "$outfile" 2>/dev/null; then
            grep "^$prefix" "$outfile" | head -1 | cut -d= -f2-
            return 0
        fi
        if ! kill -0 "$pid" 2>/dev/null; then
            echo "ERROR: Process $pid exited" >&2
            cat "$outfile" >&2
            return 1
        fi
        sleep 0.5
        elapsed=$((elapsed + 1))
    done
    echo "ERROR: Timeout waiting for $prefix" >&2
    cat "$outfile" >&2
    return 1
}

echo "=== Initializing Kubo Daemon ==="
ipfs init > /dev/null
ipfs config Addresses.API /ip4/127.0.0.1/tcp/0
ipfs config Addresses.Gateway /ip4/127.0.0.1/tcp/0
ipfs config --json Addresses.Swarm '["/ip4/127.0.0.1/tcp/0"]'
ipfs daemon > kubo_daemon.log 2>&1 &
KUBO_PID=$!
PIDS+=("$KUBO_PID")

# Wait for Kubo to be ready
sleep 5
if ! kill -0 "$KUBO_PID" 2>/dev/null; then
    echo "ERROR: Kubo daemon failed to start"
    cat kubo_daemon.log
    exit 1
fi

KUBO_PEER_ID=$(ipfs id -f="<id>")
KUBO_ADDR=$(ipfs id -f="<addrs>" | grep 127.0.0.1 | head -n 1)
echo "Kubo started: ADDR=$KUBO_ADDR PEER=$KUBO_PEER_ID"

echo "=== Kubo ↔ Python Interoperability Tests ==="

# ═══════════════════════════════════════════════════════════════
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  Test 1: Python adds 5MB file → Kubo fetches"
echo "═══════════════════════════════════════════════════════════"

LARGE_FILE=$(mktemp)
dd if=/dev/urandom of="$LARGE_FILE" bs=1048576 count=5 2>/dev/null
EXPECTED_HASH=$(shasum -a 256 "$LARGE_FILE" | awk '{print $1}')

PY_ADD_OUT1=$(mktemp)
PY_ADD_ERR1=$(mktemp)
(cd "$PYPROJECT_DIR" && uv run python "$SCRIPT_DIR/py_peer.py" add \
    --listen /ip4/127.0.0.1/tcp/0 --file "$LARGE_FILE" > "$PY_ADD_OUT1" 2>"$PY_ADD_ERR1") &
PY_PID1=$!
PIDS+=("$PY_PID1")

PY_ADDR1=$(wait_ready_and_parse "$PY_PID1" "$PY_ADD_OUT1" "ADDR=")
PY_CID1=$(wait_ready_and_parse "$PY_PID1" "$PY_ADD_OUT1" "CID=")
echo "  Python Node: ADDR=$PY_ADDR1 CID=$PY_CID1"

# Connect Kubo to Python
ipfs swarm connect "$PY_ADDR1" > /dev/null

KUBO_FETCHED=$(mktemp)
timeout 120 ipfs get "$PY_CID1" -o "$KUBO_FETCHED" > /dev/null 2>&1 || {
    fail_test "Kubo get timed out or failed"
}

if [ -f "$KUBO_FETCHED" ]; then
    KUBO_FETCHED_HASH=$(shasum -a 256 "$KUBO_FETCHED" | awk '{print $1}')
    if [ "$KUBO_FETCHED_HASH" = "$EXPECTED_HASH" ]; then
        pass_test "Kubo received correct 5MB file from Python"
    else
        fail_test "Content hash mismatch (Python→Kubo file transfer)"
    fi
fi

kill "$PY_PID1" 2>/dev/null || true
wait "$PY_PID1" 2>/dev/null || true
PIDS=("${PIDS[@]/$PY_PID1}") # Remove PY_PID1 from array

# ═══════════════════════════════════════════════════════════════
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  Test 2: Kubo adds 5MB file → Python fetches"
echo "═══════════════════════════════════════════════════════════"

KUBO_ADD_OUT=$(ipfs add -q --cid-version 1 --raw-leaves "$LARGE_FILE")
KUBO_CID2=$KUBO_ADD_OUT
echo "  Kubo Node: CID=$KUBO_CID2"

PY_FETCHED2=$(mktemp)
PY_GET_OUT2=$(mktemp)
PY_GET_ERR2=$(mktemp)

timeout 120 bash -c "cd \"$PYPROJECT_DIR\" && uv run python \"$SCRIPT_DIR/py_peer.py\" get \
    --listen /ip4/127.0.0.1/tcp/0 \
    --connect \"$KUBO_ADDR/p2p/$KUBO_PEER_ID\" --cid \"$KUBO_CID2\" --out \"$PY_FETCHED2\" > \"$PY_GET_OUT2\" 2>\"$PY_GET_ERR2\"" || {
    fail_test "Python get timed out or failed"
    cat "$PY_GET_ERR2" >&2
}

if [ -f "$PY_FETCHED2" ]; then
    PY_FETCHED_HASH2=$(shasum -a 256 "$PY_FETCHED2" | awk '{print $1}')
    if [ "$PY_FETCHED_HASH2" = "$EXPECTED_HASH" ]; then
        pass_test "Python received correct 5MB file from Kubo"
    else
        fail_test "Content hash mismatch (Kubo→Python file transfer)"
    fi
fi

# ═══════════════════════════════════════════════════════════════
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  Test 3: Python adds DAG-JSON node → Kubo fetches"
echo "═══════════════════════════════════════════════════════════"

PY_ADD_NODE_OUT=$(mktemp)
PY_ADD_NODE_ERR=$(mktemp)
(cd "$PYPROJECT_DIR" && uv run python "$SCRIPT_DIR/py_peer.py" add-node \
    --listen /ip4/127.0.0.1/tcp/0 --data '{"type":"kubo-py-interop","success":true}' > "$PY_ADD_NODE_OUT" 2>"$PY_ADD_NODE_ERR") &
PY_NODE_PID=$!
PIDS+=("$PY_NODE_PID")

PY_NODE_ADDR=$(wait_ready_and_parse "$PY_NODE_PID" "$PY_ADD_NODE_OUT" "ADDR=")
PY_NODE_CID=$(wait_ready_and_parse "$PY_NODE_PID" "$PY_ADD_NODE_OUT" "CID=")
echo "  Python Node (JSON): ADDR=$PY_NODE_ADDR CID=$PY_NODE_CID"

# Connect Kubo to Python
ipfs swarm connect "$PY_NODE_ADDR" > /dev/null

KUBO_GET_NODE_OUT=$(mktemp)
timeout 60 ipfs dag get "$PY_NODE_CID" > "$KUBO_GET_NODE_OUT" 2>/dev/null || {
    fail_test "Kubo dag get timed out or failed"
}

if grep -q "kubo-py-interop" "$KUBO_GET_NODE_OUT" 2>/dev/null; then
    pass_test "Kubo successfully fetched DAG-JSON from Python"
else
    fail_test "Node API content mismatch or timed out"
    cat "$KUBO_GET_NODE_OUT" >&2
fi

kill "$PY_NODE_PID" 2>/dev/null || true
wait "$PY_NODE_PID" 2>/dev/null || true
PIDS=("${PIDS[@]/$PY_NODE_PID}") # Remove PY_NODE_PID from array

# ═══════════════════════════════════════════════════════════════
# Cleanup temp files
rm -f "$LARGE_FILE" "$KUBO_FETCHED" "$PY_FETCHED2" "$PY_ADD_OUT1" "$PY_ADD_ERR1" "$PY_GET_OUT2" "$PY_GET_ERR2" "$PY_ADD_NODE_OUT" "$PY_ADD_NODE_ERR" "$KUBO_GET_NODE_OUT" kubo_daemon.log

# ═══════════════════════════════════════════════════════════════
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  RESULTS: $PASSED/$TOTAL passed, $FAILED failed"
echo "═══════════════════════════════════════════════════════════"

if [ $FAILED -gt 0 ]; then
    exit 1
fi
echo "  🎉 All Kubo ↔ Python interop tests passed!"
