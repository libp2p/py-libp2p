#!/usr/bin/env bash

# run_test.sh - libp2p Interoperability Test Runner (Bash)
# Tests py-libp2p <-> js-libp2p ping communication

set -e

# Colors for output
RED='\033[31m'
GREEN='\033[32m'
YELLOW='\033[33m'
BLUE='\033[34m'
CYAN='\033[36m'
RESET='\033[0m'

write_color_output() {
    local message="$1"
    local color="${2:-$RESET}"
    echo -e "${color}${message}${RESET}"
}

write_color_output "[CHECK] Checking prerequisites..." "$CYAN"
if ! command -v python3 &> /dev/null && ! command -v python &> /dev/null; then
    write_color_output "[ERROR] Python not found. Install Python 3.7+" "$RED"
    exit 1
fi

# Use python3 if available, otherwise python
PYTHON_CMD="python3"
if ! command -v python3 &> /dev/null; then
    PYTHON_CMD="python"
fi

if ! command -v node &> /dev/null; then
    write_color_output "[ERROR] Node.js not found. Install Node.js 16+" "$RED"
    exit 1
fi

write_color_output "[CHECK] Checking port 8000..." "$BLUE"
if netstat -tuln 2>/dev/null | grep -q ":8000 " || ss -tuln 2>/dev/null | grep -q ":8000 "; then
    write_color_output "[ERROR] Port 8000 in use. Free the port." "$RED"
    if command -v netstat &> /dev/null; then
        netstat -tuln | grep ":8000 " | write_color_output "$(cat)" "$YELLOW"
    elif command -v ss &> /dev/null; then
        ss -tuln | grep ":8000 " | write_color_output "$(cat)" "$YELLOW"
    fi
    exit 1
fi

write_color_output "[DEBUG] Cleaning up Python processes..." "$BLUE"
pkill -f "ping.py" 2>/dev/null || true

write_color_output "[PYTHON] Starting server on port 8000..." "$YELLOW"
cd py_node

PY_LOG_FILE="py_server_8000.log"
PY_ERR_LOG_FILE="py_server_8000.log.err"
PY_DEBUG_LOG_FILE="ping_debug.log"

rm -f "$PY_LOG_FILE" "$PY_ERR_LOG_FILE" "$PY_DEBUG_LOG_FILE"

$PYTHON_CMD -u ping.py server --port 8000 > "$PY_LOG_FILE" 2> "$PY_ERR_LOG_FILE" &
PY_PROCESS_PID=$!

write_color_output "[DEBUG] Python server PID: $PY_PROCESS_PID" "$BLUE"
write_color_output "[DEBUG] Python logs: $(pwd)/$PY_LOG_FILE, $(pwd)/$PY_ERR_LOG_FILE, $(pwd)/$PY_DEBUG_LOG_FILE" "$BLUE"

TIMEOUT_SECONDS=20
START_TIME=$(date +%s)
SERVER_STARTED=false

while [ $(($(date +%s) - START_TIME)) -lt $TIMEOUT_SECONDS ] && [ "$SERVER_STARTED" = false ]; do
    if [ -f "$PY_LOG_FILE" ]; then
        if grep -q "Server started\|Listening" "$PY_LOG_FILE" 2>/dev/null; then
            SERVER_STARTED=true
            write_color_output "[OK] Python server started" "$GREEN"
        fi
    fi
    if [ -f "$PY_ERR_LOG_FILE" ] && [ -s "$PY_ERR_LOG_FILE" ]; then
        ERR_CONTENT=$(cat "$PY_ERR_LOG_FILE" 2>/dev/null || true)
        if [ -n "$ERR_CONTENT" ]; then
            write_color_output "[DEBUG] Error log: $ERR_CONTENT" "$YELLOW"
        fi
    fi
    sleep 0.5
done

if [ "$SERVER_STARTED" = false ]; then
    write_color_output "[ERROR] Python server failed to start" "$RED"
    write_color_output "[DEBUG] Logs:" "$YELLOW"
    [ -f "$PY_LOG_FILE" ] && cat "$PY_LOG_FILE" | while read line; do write_color_output "$line" "$YELLOW"; done
    [ -f "$PY_ERR_LOG_FILE" ] && cat "$PY_ERR_LOG_FILE" | while read line; do write_color_output "$line" "$YELLOW"; done
    [ -f "$PY_DEBUG_LOG_FILE" ] && cat "$PY_DEBUG_LOG_FILE" | while read line; do write_color_output "$line" "$YELLOW"; done
    write_color_output "[DEBUG] Trying foreground run..." "$YELLOW"
    $PYTHON_CMD -u ping.py server --port 8000
    exit 1
fi

# Extract Peer ID
PEER_ID=""
MULTI_ADDR=""
if [ -f "$PY_LOG_FILE" ]; then
    CONTENT=$(cat "$PY_LOG_FILE" 2>/dev/null || true)
    PEER_ID=$(echo "$CONTENT" | grep -oP "Peer ID:\s*\K[A-Za-z0-9]+" || true)
    if [ -n "$PEER_ID" ]; then
        MULTI_ADDR="/ip4/127.0.0.1/tcp/8000/p2p/$PEER_ID"
        write_color_output "[OK] Peer ID: $PEER_ID" "$CYAN"
        write_color_output "[OK] MultiAddr: $MULTI_ADDR" "$CYAN"
    fi
fi

if [ -z "$PEER_ID" ]; then
    write_color_output "[ERROR] Could not extract Peer ID" "$RED"
    [ -f "$PY_LOG_FILE" ] && cat "$PY_LOG_FILE" | while read line; do write_color_output "$line" "$YELLOW"; done
    [ -f "$PY_ERR_LOG_FILE" ] && cat "$PY_ERR_LOG_FILE" | while read line; do write_color_output "$line" "$YELLOW"; done
    [ -f "$PY_DEBUG_LOG_FILE" ] && cat "$PY_DEBUG_LOG_FILE" | while read line; do write_color_output "$line" "$YELLOW"; done
    kill $PY_PROCESS_PID 2>/dev/null || true
    exit 1
fi

# Start JavaScript client
write_color_output "[JAVASCRIPT] Starting client..." "$YELLOW"
cd ../js_node

JS_LOG_FILE="test_js_client_to_py_server.log"
JS_ERR_LOG_FILE="test_js_client_to_py_server.log.err"

rm -f "$JS_LOG_FILE" "$JS_ERR_LOG_FILE"

node src/ping.js client "$MULTI_ADDR" 3 > "$JS_LOG_FILE" 2> "$JS_ERR_LOG_FILE" &
JS_PROCESS_PID=$!

write_color_output "[DEBUG] JavaScript client PID: $JS_PROCESS_PID" "$BLUE"
write_color_output "[DEBUG] Client logs: $(pwd)/$JS_LOG_FILE, $(pwd)/$JS_ERR_LOG_FILE" "$BLUE"

# Wait for client to complete
CLIENT_TIMEOUT=10
CLIENT_START=$(date +%s)
while kill -0 $JS_PROCESS_PID 2>/dev/null && [ $(($(date +%s) - CLIENT_START)) -lt $CLIENT_TIMEOUT ]; do
    sleep 1
done

if kill -0 $JS_PROCESS_PID 2>/dev/null; then
    write_color_output "[DEBUG] JavaScript client did not exit, terminating..." "$YELLOW"
    kill $JS_PROCESS_PID 2>/dev/null || true
fi

write_color_output "[CHECK] Results..." "$CYAN"
SUCCESS=false
if [ -f "$JS_LOG_FILE" ]; then
    JS_LOG_CONTENT=$(cat "$JS_LOG_FILE" 2>/dev/null || true)
    if echo "$JS_LOG_CONTENT" | grep -q "successful\|Ping.*successful"; then
        SUCCESS=true
        write_color_output "[SUCCESS] Ping test passed" "$GREEN"
    else
        write_color_output "[FAILED] No successful pings" "$RED"
        write_color_output "[DEBUG] Client log path: $(pwd)/$JS_LOG_FILE" "$YELLOW"
        write_color_output "Client log:" "$YELLOW"
        write_color_output "$JS_LOG_CONTENT" "$YELLOW"
        if [ -f "$JS_ERR_LOG_FILE" ]; then
            write_color_output "[DEBUG] Client error log path: $(pwd)/$JS_ERR_LOG_FILE" "$YELLOW"
            write_color_output "Client error log:" "$YELLOW"
            cat "$JS_ERR_LOG_FILE" | while read line; do write_color_output "$line" "$YELLOW"; done
        fi
        write_color_output "[DEBUG] Python server log path: $(pwd)/../py_node/$PY_LOG_FILE" "$YELLOW"
        write_color_output "Python server log:" "$YELLOW"
        if [ -f "../py_node/$PY_LOG_FILE" ]; then
            PY_LOG_CONTENT=$(cat "../py_node/$PY_LOG_FILE" 2>/dev/null || true)
            if [ -n "$PY_LOG_CONTENT" ]; then
                write_color_output "$PY_LOG_CONTENT" "$YELLOW"
            else
                write_color_output "Empty or inaccessible" "$YELLOW"
            fi
        else
            write_color_output "File not found" "$YELLOW"
        fi
        write_color_output "[DEBUG] Python server error log path: $(pwd)/../py_node/$PY_ERR_LOG_FILE" "$YELLOW"
        write_color_output "Python server error log:" "$YELLOW"
        if [ -f "../py_node/$PY_ERR_LOG_FILE" ]; then
            PY_ERR_LOG_CONTENT=$(cat "../py_node/$PY_ERR_LOG_FILE" 2>/dev/null || true)
            if [ -n "$PY_ERR_LOG_CONTENT" ]; then
                write_color_output "$PY_ERR_LOG_CONTENT" "$YELLOW"
            else
                write_color_output "Empty or inaccessible" "$YELLOW"
            fi
        else
            write_color_output "File not found" "$YELLOW"
        fi
        write_color_output "[DEBUG] Python debug log path: $(pwd)/../py_node/$PY_DEBUG_LOG_FILE" "$YELLOW"
        write_color_output "Python debug log:" "$YELLOW"
        if [ -f "../py_node/$PY_DEBUG_LOG_FILE" ]; then
            PY_DEBUG_LOG_CONTENT=$(cat "../py_node/$PY_DEBUG_LOG_FILE" 2>/dev/null || true)
            if [ -n "$PY_DEBUG_LOG_CONTENT" ]; then
                write_color_output "$PY_DEBUG_LOG_CONTENT" "$YELLOW"
            else
                write_color_output "Empty or inaccessible" "$YELLOW"
            fi
        else
            write_color_output "File not found" "$YELLOW"
        fi
    fi
fi

write_color_output "[CLEANUP] Stopping processes..." "$YELLOW"
kill $PY_PROCESS_PID 2>/dev/null || true
kill $JS_PROCESS_PID 2>/dev/null || true
cd ../

if [ "$SUCCESS" = true ]; then
    write_color_output "[SUCCESS] Test completed" "$GREEN"
    exit 0
else
    write_color_output "[FAILED] Test failed" "$RED"
    exit 1
fi
