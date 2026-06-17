#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYPROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$SCRIPT_DIR"

# Cleanup on exit
PIDS=()
cleanup() {
    for pid in "${PIDS[@]+"${PIDS[@]}"}"; do
        kill "$pid" 2>/dev/null || true
        wait "$pid" 2>/dev/null || true
    done
}
trap cleanup EXIT

# Helper: wait for line and parse output
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

echo "=== Building Go peer ==="
cd go-peer
go build -o go_peer .
cd ..

GO_PEER="./go-peer/go_peer"

# Create a 10MB test file
LARGE_FILE=$(mktemp)
dd if=/dev/urandom of="$LARGE_FILE" bs=1048576 count=10 2>/dev/null
EXPECTED_HASH=$(shasum -a 256 "$LARGE_FILE" | awk '{print $1}')

echo ""
echo "========================================="
echo "  Test 1: Go adds 10MB file -> Python fetches"
echo "========================================="

GO_OUT1=$(mktemp)
GO_ERR1=$(mktemp)
$GO_PEER none add-file "$LARGE_FILE" > "$GO_OUT1" 2>"$GO_ERR1" &
GO_PID1=$!
PIDS+=("$GO_PID1")

# Drain the stderr so Go peer doesn't hang!
tail -f "$GO_ERR1" > /dev/null 2>&1 &
TAIL_PID1=$!
PIDS+=("$TAIL_PID1")

GO_ADDR1=$(wait_ready_and_parse "$GO_PID1" "$GO_OUT1" "ADDR=")
GO_CID1=$(wait_ready_and_parse "$GO_PID1" "$GO_OUT1" "CID=")
echo "Go peer: ADDR=$GO_ADDR1 CID=$GO_CID1"

PY_OUT1=$(mktemp)
PY_ERR1=$(mktemp)
PY_FETCHED=$(mktemp)

timeout 300 bash -c "cd \"$PYPROJECT_DIR\" && uv run python \"$SCRIPT_DIR/py_peer.py\" get \
    --connect \"$GO_ADDR1\" --cid \"$GO_CID1\" --out \"$PY_FETCHED\" > \"$PY_OUT1\" 2>\"$PY_ERR1\"" || {
    echo "Python get timed out or failed"
    echo "--- Python stderr ---"
    cat "$PY_ERR1"
    exit 1
}

PY_FETCHED_HASH=$(shasum -a 256 "$PY_FETCHED" | awk '{print $1}')

if [ "$PY_FETCHED_HASH" = "$EXPECTED_HASH" ]; then
    echo "PASS: Python received correct 10MB file from Go"
else
    echo "FAIL: Content mismatch"
    exit 1
fi

kill "$GO_PID1" "$TAIL_PID1" 2>/dev/null || true
wait "$GO_PID1" "$TAIL_PID1" 2>/dev/null || true
PIDS=()

echo ""
echo "========================================="
echo "  Test 2: Python adds 10MB file -> Go fetches"
echo "========================================="

PY_ADD_OUT2=$(mktemp)
PY_ADD_ERR2=$(mktemp)
(cd "$PYPROJECT_DIR" && uv run python "$SCRIPT_DIR/py_peer.py" add \
    --listen /ip4/127.0.0.1/tcp/0 --file "$LARGE_FILE" > "$PY_ADD_OUT2" 2>"$PY_ADD_ERR2") &
PY_PID2=$!
PIDS+=("$PY_PID2")

PY_ADDR2=$(wait_ready_and_parse "$PY_PID2" "$PY_ADD_OUT2" "ADDR=")
PY_CID2=$(wait_ready_and_parse "$PY_PID2" "$PY_ADD_OUT2" "CID=")
echo "Python peer: ADDR=$PY_ADDR2 CID=$PY_CID2"

if [ "$PY_CID2" = "$GO_CID1" ]; then
    echo "CID match: Go and Python produce same CID for 10MB file"
else
    echo "WARNING: CID mismatch (Go=$GO_CID1 Python=$PY_CID2)"
fi

GO_GET_OUT2=$(mktemp)
GO_GET_ERR2=$(mktemp)
GO_FETCHED=$(mktemp)

# Drain the stderr so Python peer doesn't hang!
tail -f "$PY_ADD_ERR2" > /dev/null 2>&1 &
TAIL_PID2=$!
PIDS+=("$TAIL_PID2")

timeout 300 $GO_PEER "$PY_ADDR2" fetch-file "$PY_CID2" "$GO_FETCHED" > "$GO_GET_OUT2" 2>"$GO_GET_ERR2" || {
    echo "Go get timed out or failed"
    echo "--- Go stderr ---"
    cat "$GO_GET_ERR2"
    echo "--- Python stderr ---"
    cat "$PY_ADD_ERR2"
    exit 1
}

GO_FETCHED_HASH=$(shasum -a 256 "$GO_FETCHED" | awk '{print $1}')

if [ "$GO_FETCHED_HASH" = "$EXPECTED_HASH" ]; then
    echo "PASS: Go received correct 10MB file from Python"
else
    echo "FAIL: Content mismatch"
    exit 1
fi

kill "$PY_PID2" "$TAIL_PID2" 2>/dev/null || true
wait "$PY_PID2" "$TAIL_PID2" 2>/dev/null || true
PIDS=()

rm -f "$LARGE_FILE" "$PY_FETCHED" "$GO_FETCHED"

echo ""
echo "========================================="
echo "  All 10MB Interop tests passed!"
echo "========================================="
