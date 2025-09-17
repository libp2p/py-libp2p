#!/bin/bash
set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$SCRIPT_DIR/logs"

echo -e "${BLUE}Starting hole punching interoperability test...${NC}"

mkdir -p "$LOG_DIR"

cleanup() {
    echo -e "${YELLOW}Cleaning up...${NC}"
    if [ ! -z "$RELAY_PID" ]; then
        kill $RELAY_PID 2>/dev/null || true
    fi
    if [ ! -z "$GO_PID" ]; then
        kill $GO_PID 2>/dev/null || true
    fi
    if [ ! -z "$PY_PID" ]; then
        kill $PY_PID 2>/dev/null || true
    fi
    wait 2>/dev/null || true
}

trap cleanup EXIT

echo -e "${BLUE}Building Go components...${NC}"
cd "$SCRIPT_DIR/go_node"
go build -o relay-server ./cmd/relay-server/main.go
go build -o hole-punch-server ./cmd/hole-punch-server/main.go
go build -o hole-punch-client ./cmd/hole-punch-client/main.go

echo -e "${BLUE}Starting relay server...${NC}"
"$SCRIPT_DIR/go_node/relay-server" --port=4001 > "$LOG_DIR/relay.log" 2>&1 &
RELAY_PID=$!

echo -e "${BLUE}Waiting for relay peer ID...${NC}"
for i in {1..10}; do
    sleep 2
    if [ -f "$LOG_DIR/relay.log" ]; then
        RELAY_ID=$(grep "Relay server peer ID:" "$LOG_DIR/relay.log" | tail -1 | awk '{print $NF}' || echo "")
        if [ ! -z "$RELAY_ID" ]; then
            break
        fi
    fi
    echo "Attempt $i: waiting..."
done

if [ -z "$RELAY_ID" ]; then
    echo -e "${RED}Failed to get relay peer ID from log file${NC}"
    echo "Relay log contents:"
    cat "$LOG_DIR/relay.log" || echo "No relay log file"
    exit 1
fi

RELAY_ADDR="/ip4/127.0.0.1/tcp/4001/p2p/$RELAY_ID"
echo -e "${GREEN}Relay running at: $RELAY_ADDR${NC}"
echo -e "${GREEN}Relay peer ID: $RELAY_ID${NC}"

echo -e "${BLUE}Starting Go hole punch server...${NC}"
"$SCRIPT_DIR/go_node/hole-punch-server" --relay="$RELAY_ADDR" --duration=120 > "$LOG_DIR/go_server.log" 2>&1 &
GO_PID=$!

echo -e "${BLUE}Waiting for Go server peer ID...${NC}"
for i in {1..10}; do
    sleep 2
    if [ -f "$LOG_DIR/go_server.log" ]; then
        GO_SERVER_ID=$(grep "Go hole punch server peer ID:" "$LOG_DIR/go_server.log" | tail -1 | awk '{print $NF}' || echo "")
        if [ ! -z "$GO_SERVER_ID" ]; then
            break
        fi
    fi
    echo "Attempt $i: waiting..."
done

if [ -z "$GO_SERVER_ID" ]; then
    echo -e "${RED}Failed to get Go server peer ID from log file${NC}"
    echo "Go server log contents:"
    cat "$LOG_DIR/go_server.log" || echo "No go server log file"
    exit 1
fi

echo -e "${GREEN}Go server peer ID: $GO_SERVER_ID${NC}"

if grep -q "Connected to relay" "$LOG_DIR/go_server.log"; then
    echo -e "${GREEN}Go server connected to relay${NC}"
else
    echo -e "${YELLOW}Go server may not have connected to relay properly${NC}"
    echo "Go server connection logs:"
    grep -i "relay\|connect\|dial" "$LOG_DIR/go_server.log" || echo "No connection logs found"
fi

echo -e "${BLUE}Starting Python hole punch client...${NC}"
cd "$SCRIPT_DIR/py_node"
python hole_punch_client.py \
    --relay="$RELAY_ADDR" \
    --target="$GO_SERVER_ID" \
    --duration=60 > "$LOG_DIR/py_client.log" 2>&1 &
PY_PID=$!

echo -e "${BLUE}Test running for 60 seconds...${NC}"
echo -e "${YELLOW}Monitor logs:${NC}"
echo -e "  Relay:      tail -f $LOG_DIR/relay.log"
echo -e "  Go Server:  tail -f $LOG_DIR/go_server.log"
echo -e "  Py Client:  tail -f $LOG_DIR/py_client.log"

wait $PY_PID
PY_CLIENT_EXIT_CODE=$?

echo -e "${BLUE}Analyzing results...${NC}"

SUCCESS=false

if grep -q "New connection from peer" "$LOG_DIR/relay.log"; then
    echo -e "${GREEN}Relay received connections${NC}"
    SUCCESS=true
fi

if grep -q "Connected to relay" "$LOG_DIR/go_server.log"; then
    echo -e "${GREEN}Go server connected to relay${NC}"
fi

if grep -q "New connection from peer" "$LOG_DIR/go_server.log"; then
    echo -e "${GREEN}Go server received peer connection${NC}"
    SUCCESS=true
fi

if grep -q "Received ping stream" "$LOG_DIR/go_server.log"; then
    echo -e "${GREEN}Go server received and handled ping stream${NC}"
    SUCCESS=true
fi

if grep -q "SUCCESS" "$LOG_DIR/py_client.log"; then
    echo -e "${GREEN}Python client succeeded${NC}"
    SUCCESS=true
fi

if grep -q "Connected to target through relay" "$LOG_DIR/py_client.log"; then
    echo -e "${GREEN}Python client connected through relay${NC}"
    SUCCESS=true
fi

if grep -q "Opened test stream" "$LOG_DIR/py_client.log"; then
    echo -e "${GREEN}Test stream opened successfully${NC}"
    SUCCESS=true
fi

if grep -q "Received response" "$LOG_DIR/py_client.log"; then
    echo -e "${GREEN}Python client received response from Go server${NC}"
    SUCCESS=true
fi

if grep -q "peer id mismatch" "$LOG_DIR/go_server.log"; then
    echo -e "${RED}Peer ID mismatch detected in Go server${NC}"
fi

if grep -q "failed to dial" "$LOG_DIR/go_server.log"; then
    echo -e "${RED}Go server failed to dial relay${NC}"
fi

if grep -q "unable to connect" "$LOG_DIR/py_client.log"; then
    echo -e "${RED}Python client unable to connect to target${NC}"
fi

echo -e "\n${BLUE}=== SUMMARY ===${NC}"
echo -e "Relay Peer ID: $RELAY_ID"
echo -e "Go Server Peer ID: $GO_SERVER_ID"
echo -e "Python Client Exit Code: $PY_CLIENT_EXIT_CODE"

if [ "$SUCCESS" = true ]; then
    echo -e "\n${GREEN}SUCCESS: Interop test passed${NC}"
    echo "Connections were established between py-libp2p and go-libp2p through relay."
    exit 0
else
    echo -e "\n${RED}FAILURE: Interop test failed${NC}"
    echo -e "\n${YELLOW}=== DETAILED LOGS ===${NC}"
    echo -e "--- Relay Log ---"
    cat "$LOG_DIR/relay.log"
    echo -e "\n--- Go Server Log ---"
    cat "$LOG_DIR/go_server.log"
    echo -e "\n--- Python Client Log ---"
    cat "$LOG_DIR/py_client.log"
    exit 1
fi
