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

# ═══════════════════════════════════════════════════════════════
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  Test 1: Go adds 10MB file → Python fetches"
echo "═══════════════════════════════════════════════════════════"

LARGE_FILE=$(mktemp)
dd if=/dev/urandom of="$LARGE_FILE" bs=1048576 count=10 2>/dev/null
EXPECTED_HASH=$(shasum -a 256 "$LARGE_FILE" | awk '{print $1}')

GO_OUT1=$(mktemp)
GO_ERR1=$(mktemp)
$GO_PEER none add-file "$LARGE_FILE" > "$GO_OUT1" 2>"$GO_ERR1" &
GO_PID1=$!
PIDS+=("$GO_PID1")

tail -f "$GO_ERR1" > /dev/null 2>&1 &
TAIL_PID1=$!
PIDS+=("$TAIL_PID1")

GO_ADDR1=$(wait_ready_and_parse "$GO_PID1" "$GO_OUT1" "ADDR=")
GO_CID1=$(wait_ready_and_parse "$GO_PID1" "$GO_OUT1" "CID=")
echo "  Go peer: ADDR=$GO_ADDR1 CID=$GO_CID1"

PY_FETCHED=$(mktemp)
PY_OUT1=$(mktemp)
PY_ERR1=$(mktemp)

timeout 300 bash -c "cd \"$PYPROJECT_DIR\" && uv run python \"$SCRIPT_DIR/py_peer.py\" get \
    --connect \"$GO_ADDR1\" --cid \"$GO_CID1\" --out \"$PY_FETCHED\" > \"$PY_OUT1\" 2>\"$PY_ERR1\"" || {
    fail_test "Python get timed out or failed"
    cat "$PY_ERR1" >&2
}

if [ -f "$PY_FETCHED" ]; then
    PY_FETCHED_HASH=$(shasum -a 256 "$PY_FETCHED" | awk '{print $1}')
    if [ "$PY_FETCHED_HASH" = "$EXPECTED_HASH" ]; then
        pass_test "Python received correct 10MB file from Go"
    else
        fail_test "Content hash mismatch (Go→Python file transfer)"
    fi
fi

kill "$GO_PID1" "$TAIL_PID1" 2>/dev/null || true
wait "$GO_PID1" "$TAIL_PID1" 2>/dev/null || true
PIDS=()

# ═══════════════════════════════════════════════════════════════
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  Test 2: Python adds 10MB file → Go fetches"
echo "═══════════════════════════════════════════════════════════"

PY_ADD_OUT2=$(mktemp)
PY_ADD_ERR2=$(mktemp)
(cd "$PYPROJECT_DIR" && uv run python "$SCRIPT_DIR/py_peer.py" add \
    --listen /ip4/127.0.0.1/tcp/0 --file "$LARGE_FILE" > "$PY_ADD_OUT2" 2>"$PY_ADD_ERR2") &
PY_PID2=$!
PIDS+=("$PY_PID2")

PY_ADDR2=$(wait_ready_and_parse "$PY_PID2" "$PY_ADD_OUT2" "ADDR=")
PY_CID2=$(wait_ready_and_parse "$PY_PID2" "$PY_ADD_OUT2" "CID=")
echo "  Python peer: ADDR=$PY_ADDR2 CID=$PY_CID2"

if [ "$PY_CID2" = "$GO_CID1" ]; then
    pass_test "CID match: Go and Python produce same CID for 10MB file"
else
    echo "  WARNING: CID mismatch (Go=$GO_CID1 Python=$PY_CID2)"
fi

GO_GET_OUT2=$(mktemp)
GO_GET_ERR2=$(mktemp)
GO_FETCHED=$(mktemp)

tail -f "$PY_ADD_ERR2" > /dev/null 2>&1 &
TAIL_PID2=$!
PIDS+=("$TAIL_PID2")

timeout 300 $GO_PEER "$PY_ADDR2" fetch-file "$PY_CID2" "$GO_FETCHED" > "$GO_GET_OUT2" 2>"$GO_GET_ERR2" || {
    fail_test "Go get timed out or failed"
    cat "$GO_GET_ERR2" >&2
}

if [ -f "$GO_FETCHED" ]; then
    GO_FETCHED_HASH=$(shasum -a 256 "$GO_FETCHED" | awk '{print $1}')
    if [ "$GO_FETCHED_HASH" = "$EXPECTED_HASH" ]; then
        pass_test "Go received correct 10MB file from Python"
    else
        fail_test "Content hash mismatch (Python→Go file transfer)"
    fi
fi

kill "$PY_PID2" "$TAIL_PID2" 2>/dev/null || true
wait "$PY_PID2" "$TAIL_PID2" 2>/dev/null || true
PIDS=()

# ═══════════════════════════════════════════════════════════════
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  Test 3: CID generation parity (1MB file)"
echo "═══════════════════════════════════════════════════════════"

SMALL_FILE=$(mktemp)
dd if=/dev/urandom of="$SMALL_FILE" bs=1048576 count=1 2>/dev/null

GO_OUT3=$(mktemp)
GO_ERR3=$(mktemp)
$GO_PEER none add-file "$SMALL_FILE" > "$GO_OUT3" 2>"$GO_ERR3" &
GO_PID3=$!
PIDS+=("$GO_PID3")

GO_CID3=$(wait_ready_and_parse "$GO_PID3" "$GO_OUT3" "CID=")

PY_ADD_OUT3=$(mktemp)
PY_ADD_ERR3=$(mktemp)
(cd "$PYPROJECT_DIR" && uv run python "$SCRIPT_DIR/py_peer.py" add \
    --listen /ip4/127.0.0.1/tcp/0 --file "$SMALL_FILE" > "$PY_ADD_OUT3" 2>"$PY_ADD_ERR3") &
PY_PID3=$!
PIDS+=("$PY_PID3")

PY_CID3=$(wait_ready_and_parse "$PY_PID3" "$PY_ADD_OUT3" "CID=")

if [ "$PY_CID3" = "$GO_CID3" ]; then
    pass_test "CID match for 1MB file (Go=$GO_CID3 Python=$PY_CID3)"
else
    fail_test "CID mismatch for 1MB (Go=$GO_CID3 Python=$PY_CID3)"
fi

kill "$GO_PID3" "$PY_PID3" 2>/dev/null || true
wait "$GO_PID3" "$PY_PID3" 2>/dev/null || true
PIDS=()

# ═══════════════════════════════════════════════════════════════
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  Test 4: Python add-get-remove (DAGService lifecycle)"
echo "═══════════════════════════════════════════════════════════"

PY_AGR_OUT=$(mktemp)
PY_AGR_ERR=$(mktemp)
timeout 60 bash -c "cd \"$PYPROJECT_DIR\" && uv run python \"$SCRIPT_DIR/py_peer.py\" add-get-remove \
    --data 'lifecycle-test-content' > \"$PY_AGR_OUT\" 2>\"$PY_AGR_ERR\"" || true

PY_AGR_RESULT=$(grep "ADD_GET_REMOVE_RESULT=" "$PY_AGR_OUT" 2>/dev/null | cut -d= -f2 || echo "MISSING")

if [ "$PY_AGR_RESULT" = "PASS" ]; then
    pass_test "Python add-get-remove lifecycle works correctly"
else
    fail_test "Python add-get-remove (result=$PY_AGR_RESULT)"
    cat "$PY_AGR_OUT" >&2
fi

# ═══════════════════════════════════════════════════════════════
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  Test 5: Python Pin + GC round-trip"
echo "═══════════════════════════════════════════════════════════"

PY_PINGC_OUT=$(mktemp)
PY_PINGC_ERR=$(mktemp)
timeout 60 bash -c "cd \"$PYPROJECT_DIR\" && uv run python \"$SCRIPT_DIR/py_peer.py\" pin-gc \
    > \"$PY_PINGC_OUT\" 2>\"$PY_PINGC_ERR\"" || true

PY_PINGC_RESULT=$(grep "PIN_GC_RESULT=" "$PY_PINGC_OUT" 2>/dev/null | cut -d= -f2 || echo "MISSING")
GC_RECLAIMED=$(grep "GC_RECLAIMED=" "$PY_PINGC_OUT" 2>/dev/null | cut -d= -f2 || echo "?")
GC_RETAINED=$(grep "GC_RETAINED=" "$PY_PINGC_OUT" 2>/dev/null | cut -d= -f2 || echo "?")

if [ "$PY_PINGC_RESULT" = "PASS" ]; then
    pass_test "Pin+GC: pinned block retained, unpinned blocks reclaimed (reclaimed=$GC_RECLAIMED retained=$GC_RETAINED)"
else
    fail_test "Pin+GC round-trip (result=$PY_PINGC_RESULT reclaimed=$GC_RECLAIMED retained=$GC_RETAINED)"
    cat "$PY_PINGC_OUT" >&2
    cat "$PY_PINGC_ERR" >&2
fi

# ═══════════════════════════════════════════════════════════════
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  Test 6: Node API — Python add → Python fetch (dag-json)"
echo "═══════════════════════════════════════════════════════════"

PY_ADD_NODE_OUT=$(mktemp)
PY_ADD_NODE_ERR=$(mktemp)
(cd "$PYPROJECT_DIR" && uv run python "$SCRIPT_DIR/py_peer.py" add-node \
    --listen /ip4/127.0.0.1/tcp/0 --data '{"message":"hello from node api","version":42}' > "$PY_ADD_NODE_OUT" 2>"$PY_ADD_NODE_ERR") &
PY_ADD_NODE_PID=$!
PIDS+=("$PY_ADD_NODE_PID")

PY_NODE_ADDR=$(wait_ready_and_parse "$PY_ADD_NODE_PID" "$PY_ADD_NODE_OUT" "ADDR=")
PY_NODE_CID=$(wait_ready_and_parse "$PY_ADD_NODE_PID" "$PY_ADD_NODE_OUT" "CID=")
echo "  Python node peer: ADDR=$PY_NODE_ADDR CID=$PY_NODE_CID"

PY_GET_NODE_OUT=$(mktemp)
PY_GET_NODE_ERR=$(mktemp)
timeout 120 bash -c "cd \"$PYPROJECT_DIR\" && uv run python \"$SCRIPT_DIR/py_peer.py\" get-node \
    --listen /ip4/127.0.0.1/tcp/0 \
    --connect \"$PY_NODE_ADDR\" --cid \"$PY_NODE_CID\" > \"$PY_GET_NODE_OUT\" 2>\"$PY_GET_NODE_ERR\"" || true

if grep -q "DONE_FETCH_NODE.*hello from node api" "$PY_GET_NODE_OUT" 2>/dev/null; then
    pass_test "Python ↔ Python generic DAG-JSON node exchange"
else
    fail_test "Node API content mismatch or timed out"
    cat "$PY_GET_NODE_OUT" >&2
fi

kill "$PY_ADD_NODE_PID" 2>/dev/null || true
wait "$PY_ADD_NODE_PID" 2>/dev/null || true
PIDS=()

# ═══════════════════════════════════════════════════════════════
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  Test 7: Go blockstore roundtrip (add + has + fetch + DAG walk)"
echo "═══════════════════════════════════════════════════════════"

BS_FILE=$(mktemp)
dd if=/dev/urandom of="$BS_FILE" bs=1048576 count=2 2>/dev/null

GO_BS_OUT=$(mktemp)
GO_BS_ERR=$(mktemp)
timeout 120 $GO_PEER none blockstore-roundtrip "$BS_FILE" > "$GO_BS_OUT" 2>"$GO_BS_ERR" || true

GO_HAS_BLOCK=$(grep "HAS_BLOCK=" "$GO_BS_OUT" 2>/dev/null | cut -d= -f2 || echo "")
GO_CONTENT_SIZE=$(grep "CONTENT_SIZE=" "$GO_BS_OUT" 2>/dev/null | cut -d= -f2 || echo "")
GO_DAG_COUNT=$(grep "DAG_NODE_COUNT=" "$GO_BS_OUT" 2>/dev/null | cut -d= -f2 || echo "")

EXPECTED_SIZE=$(wc -c < "$BS_FILE" | tr -d ' ')

if [ "$GO_HAS_BLOCK" = "true" ] && [ "$GO_CONTENT_SIZE" = "$EXPECTED_SIZE" ]; then
    pass_test "Go blockstore roundtrip (size=$GO_CONTENT_SIZE dag_nodes=$GO_DAG_COUNT)"
else
    fail_test "Go blockstore roundtrip (has=$GO_HAS_BLOCK size=$GO_CONTENT_SIZE expected=$EXPECTED_SIZE)"
fi

# ═══════════════════════════════════════════════════════════════
# Cleanup temp files
rm -f "$LARGE_FILE" "$PY_FETCHED" "$GO_FETCHED" "$SMALL_FILE" "$BS_FILE"

# ═══════════════════════════════════════════════════════════════
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  RESULTS: $PASSED/$TOTAL passed, $FAILED failed"
echo "═══════════════════════════════════════════════════════════"

if [ $FAILED -gt 0 ]; then
    exit 1
fi
echo "  🎉 All interop tests passed!"
