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
cleanup() {
    for pid in "${PIDS[@]+"${PIDS[@]}"}"; do
        kill "$pid" 2>/dev/null || true
        wait "$pid" 2>/dev/null || true
    done
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

echo "=== Python ↔ Python Interoperability Tests ==="

# ═══════════════════════════════════════════════════════════════
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  Test 1: Python Node 1 adds 5MB file → Python Node 2 fetches"
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
echo "  Python Node 1: ADDR=$PY_ADDR1 CID=$PY_CID1"

PY_FETCHED1=$(mktemp)
PY_GET_OUT1=$(mktemp)
PY_GET_ERR1=$(mktemp)

timeout 120 bash -c "cd \"$PYPROJECT_DIR\" && uv run python \"$SCRIPT_DIR/py_peer.py\" get \
    --listen /ip4/127.0.0.1/tcp/0 \
    --connect \"$PY_ADDR1\" --cid \"$PY_CID1\" --out \"$PY_FETCHED1\" > \"$PY_GET_OUT1\" 2>\"$PY_GET_ERR1\"" || {
    fail_test "Python 2 get timed out or failed"
    cat "$PY_GET_ERR1" >&2
}

if [ -f "$PY_FETCHED1" ]; then
    PY_FETCHED_HASH1=$(shasum -a 256 "$PY_FETCHED1" | awk '{print $1}')
    if [ "$PY_FETCHED_HASH1" = "$EXPECTED_HASH" ]; then
        pass_test "Python 2 received correct 5MB file from Python 1"
    else
        fail_test "Content hash mismatch (Python→Python file transfer)"
    fi
fi

kill "$PY_PID1" 2>/dev/null || true
wait "$PY_PID1" 2>/dev/null || true
PIDS=()

# ═══════════════════════════════════════════════════════════════
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  Test 2: Python Node 1 adds DAG-JSON node → Python Node 2 fetches"
echo "═══════════════════════════════════════════════════════════"

PY_ADD_NODE_OUT=$(mktemp)
PY_ADD_NODE_ERR=$(mktemp)
(cd "$PYPROJECT_DIR" && uv run python "$SCRIPT_DIR/py_peer.py" add-node \
    --listen /ip4/127.0.0.1/tcp/0 --data '{"type":"py-py-interop","success":true}' > "$PY_ADD_NODE_OUT" 2>"$PY_ADD_NODE_ERR") &
PY_NODE_PID=$!
PIDS+=("$PY_NODE_PID")

PY_NODE_ADDR=$(wait_ready_and_parse "$PY_NODE_PID" "$PY_ADD_NODE_OUT" "ADDR=")
PY_NODE_CID=$(wait_ready_and_parse "$PY_NODE_PID" "$PY_ADD_NODE_OUT" "CID=")
echo "  Python Node 1 (JSON): ADDR=$PY_NODE_ADDR CID=$PY_NODE_CID"

PY_GET_NODE_OUT=$(mktemp)
PY_GET_NODE_ERR=$(mktemp)
timeout 60 bash -c "cd \"$PYPROJECT_DIR\" && uv run python \"$SCRIPT_DIR/py_peer.py\" get-node \
    --listen /ip4/127.0.0.1/tcp/0 \
    --connect \"$PY_NODE_ADDR\" --cid \"$PY_NODE_CID\" > \"$PY_GET_NODE_OUT\" 2>\"$PY_GET_NODE_ERR\"" || true

if grep -q "DONE_FETCH_NODE.*py-py-interop" "$PY_GET_NODE_OUT" 2>/dev/null; then
    pass_test "Python Node 2 successfully fetched DAG-JSON from Python Node 1"
else
    fail_test "Node API content mismatch or timed out"
    cat "$PY_GET_NODE_OUT" >&2
    cat "$PY_GET_NODE_ERR" >&2
fi

kill "$PY_NODE_PID" 2>/dev/null || true
wait "$PY_NODE_PID" 2>/dev/null || true
PIDS=()

# ═══════════════════════════════════════════════════════════════
# Cleanup temp files
rm -f "$LARGE_FILE" "$PY_FETCHED1"

# ═══════════════════════════════════════════════════════════════
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  RESULTS: $PASSED/$TOTAL passed, $FAILED failed"
echo "═══════════════════════════════════════════════════════════"

if [ $FAILED -gt 0 ]; then
    exit 1
fi
echo "  🎉 All Python-to-Python interop tests passed!"
