#!/bin/bash
set -e

REDIS_HOST="${REDIS_HOST:-localhost}"
REDIS_PORT="${REDIS_PORT:-6379}"
PY_LISTEN_PORT=9090
GO_LISTEN_PORT=9091
TEST_DIR="$(cd "$(dirname "${BASH_SOURCE}")" && pwd)"
VENV_DIR="$TEST_DIR/../../../venv"

PY_LISTENER_PID=""
GO_DIALER_PID=""

cleanup() {
    if [ -n "$PY_LISTENER_PID" ]; then
        kill $PY_LISTENER_PID 2>/dev/null || true
    fi
    
    if [ -n "$GO_DIALER_PID" ]; then
        kill $GO_DIALER_PID 2>/dev/null || true
    fi
    
    redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" DEL \
        "interop:webrtc:listener:addr" \
        "interop:webrtc:listener:ready" \
        "interop:webrtc:connection:status" \
        "interop:webrtc:ping:status" \
        >/dev/null 2>&1 || true
}

trap cleanup EXIT INT TERM

if ! redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" ping >/dev/null 2>&1; then
    echo "Redis is not running at $REDIS_HOST:$REDIS_PORT"
    exit 1
fi

if [ ! -d "$VENV_DIR" ]; then
    echo "Python venv not found: $VENV_DIR"
    exit 1
fi

if [ ! -f "$TEST_DIR/go_peer" ]; then
    echo "Go peer binary not found"
    exit 1
fi

redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" DEL \
    "interop:webrtc:listener:addr" \
    "interop:webrtc:listener:ready" \
    "interop:webrtc:connection:status" \
    "interop:webrtc:ping:status" \
    >/dev/null 2>&1 || true

source "$VENV_DIR/bin/activate"

python "$TEST_DIR/py_peer.py" \
    --role listener \
    --port "$PY_LISTEN_PORT" \
    --redis-host "$REDIS_HOST" \
    --redis-port "$REDIS_PORT" \
    >/tmp/py-listener.log 2>&1 &
PY_LISTENER_PID=$!

sleep 3

"$TEST_DIR/go_peer" \
    --role dialer \
    --port "$GO_LISTEN_PORT" \
    --redis-host "$REDIS_HOST" \
    --redis-port "$REDIS_PORT" \
    >/tmp/go-dialer.log 2>&1 &
GO_DIALER_PID=$!

sleep 2

python "$TEST_DIR/test_runner.py"
TEST_RESULT=$?

echo "Test result: $TEST_RESULT"
echo "Python listener log: /tmp/py-listener.log"
echo "Go dialer log: /tmp/go-dialer.log"

exit $TEST_RESULT
