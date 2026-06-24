#!/usr/bin/env bash
# Full ML-KEM-768 interop triangle test.
#
# Tests all three pairings:
#   1. Rust listener + Python dialer
#   2. Rust listener + JS dialer
#   3. Python listener + JS dialer
#
# Protocol: Noise_XXhfs_25519+ML-KEM-768_ChaChaPoly_SHA256
#
# Prerequisites:
#   - Rust listener compiled:
#       cargo build --example noise_hfs_listener --features mlkem-hfs
#   - JS built:
#       cd js-libp2p-noise && pnpm build
#   - Python env: pip install -e py-libp2p/   (PQC-Research version)
#
# Windows note: Run via Git Bash or WSL.
#   bash py-libp2p/scripts/interop_all.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PQC_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

RUST_BIN="${REPO_ROOT}/rust-libp2p/target/debug/examples/noise_hfs_listener"
JS_DIR="${REPO_ROOT}/js-libp2p-noise"
PY_DIR="${REPO_ROOT}/py-libp2p"

# On Windows the binary has .exe extension
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" || -f "${RUST_BIN}.exe" ]]; then
    RUST_BIN="${RUST_BIN}.exe"
fi

if [[ ! -f "$RUST_BIN" ]]; then
    echo "ERROR: Rust binary not found at $RUST_BIN"
    echo "Build it first: cargo build --example noise_hfs_listener --features mlkem-hfs"
    exit 1
fi

PASS=0
FAIL=0

run_pair() {
    local name="$1"
    local listener_type="$2"   # "rust", "python"
    local listener_port="$3"
    local dialer_type="$4"     # "python", "js"

    echo ""
    echo "=== $name ==="

    # Start listener
    local listener_log
    listener_log="$(mktemp)"

    if [[ "$listener_type" == "rust" ]]; then
        "$RUST_BIN" "$listener_port" > "$listener_log" 2>&1 &
    else
        (cd "$PY_DIR" && python scripts/interop_listen_mlkem768.py --port "$listener_port") > "$listener_log" 2>&1 &
    fi
    local LISTENER_PID=$!

    # Wait for READY signal (poll up to 10 seconds)
    local waited=0
    while ! grep -q "READY" "$listener_log" 2>/dev/null; do
        sleep 0.5
        waited=$((waited + 1))
        if [[ $waited -ge 20 ]]; then
            echo "FAIL: $name (listener did not print READY within 10s)"
            cat "$listener_log" >&2
            kill "$LISTENER_PID" 2>/dev/null || true
            rm -f "$listener_log"
            FAIL=$((FAIL + 1))
            return
        fi
    done

    # Run dialer and capture output
    local dialer_out
    dialer_out="$(mktemp)"
    local dialer_ok=0

    if [[ "$dialer_type" == "js" ]]; then
        node "${JS_DIR}/scripts/noise-hfs-dial.mjs" --port "$listener_port" > "$dialer_out" 2>&1 && dialer_ok=1 || dialer_ok=0
    else
        (cd "$PY_DIR" && python scripts/interop_dial_mlkem768.py --port "$listener_port") > "$dialer_out" 2>&1 && dialer_ok=1 || dialer_ok=0
    fi

    if [[ $dialer_ok -eq 1 ]] && grep -q "PEER" "$dialer_out"; then
        echo "PASS: $name"
        PASS=$((PASS + 1))
        grep "PEER" "$dialer_out"
    else
        echo "FAIL: $name"
        echo "  Dialer output:"
        cat "$dialer_out" >&2
        echo "  Listener output:"
        cat "$listener_log" >&2
        FAIL=$((FAIL + 1))
    fi

    kill "$LISTENER_PID" 2>/dev/null || true
    wait "$LISTENER_PID" 2>/dev/null || true
    rm -f "$listener_log" "$dialer_out"
    sleep 1
}

echo "=== ML-KEM-768 Triangle Interop Test ==="
echo "Protocol: Noise_XXhfs_25519+ML-KEM-768_ChaChaPoly_SHA256"

# 1. Rust listener + Python dialer
run_pair "Rust listener + Python dialer" "rust"   9990 "python"

# 2. Rust listener + JS dialer
run_pair "Rust listener + JS dialer"    "rust"   9991 "js"

# 3. Python listener + JS dialer
run_pair "Python listener + JS dialer"  "python" 9992 "js"

echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="
[ "$FAIL" -eq 0 ]
