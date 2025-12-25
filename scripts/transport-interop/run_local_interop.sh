#!/usr/bin/env bash
# Local interop test runner for chromium-rust-v0.53 x python-v0.4 (ws, noise, mplex)
# This script orchestrates the test without Docker or Redis

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
RUST_PROJECT_ROOT="${RUST_PROJECT_ROOT:-$HOME/PNL_Launchpad_Curriculum/Libp2p/rust-libp2p}"
ADDRESS_FILE="/tmp/libp2p_listener_addr.txt"
COORDINATOR_PORT=8080
TEST_TIMEOUT=30

# Use venv Python if available
if [ -d "$PYTHON_PROJECT_ROOT/venv" ]; then
    PYTHON_CMD="$PYTHON_PROJECT_ROOT/venv/bin/python3"
    echo -e "${CYAN}Using venv Python: $PYTHON_CMD${NC}"
else
    PYTHON_CMD="python3"
fi

# Cleanup function
cleanup() {
    echo -e "${YELLOW}Cleaning up...${NC}"
    kill $PYTHON_LISTENER_PID 2>/dev/null || true
    kill $COORDINATOR_PID 2>/dev/null || true
    kill $RUST_DIALER_PID 2>/dev/null || true
    rm -f "$ADDRESS_FILE"
    wait 2>/dev/null || true
}

trap cleanup EXIT INT TERM

# Check prerequisites
echo -e "${CYAN}Checking prerequisites...${NC}"

if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Error: python3 not found${NC}"
    exit 1
fi

if ! command -v cargo &> /dev/null; then
    echo -e "${RED}Error: cargo (Rust) not found${NC}"
    exit 1
fi

if ! command -v chromedriver &> /dev/null && ! command -v chromedriver.exe &> /dev/null; then
    echo -e "${YELLOW}Warning: chromedriver not found in PATH${NC}"
    echo -e "${YELLOW}Please install chromedriver compatible with your Chrome version${NC}"
    exit 1
fi

# Check if Rust project exists
if [ ! -d "$RUST_PROJECT_ROOT/interop-tests" ]; then
    echo -e "${RED}Error: Rust interop-tests not found at $RUST_PROJECT_ROOT/interop-tests${NC}"
    echo -e "${YELLOW}Please set RUST_PROJECT_ROOT environment variable or ensure rust-libp2p is checked out${NC}"
    exit 1
fi

# Check if wasm package is built
if [ ! -d "$RUST_PROJECT_ROOT/interop-tests/pkg" ]; then
    echo -e "${YELLOW}WASM package not found. Building...${NC}"
    cd "$RUST_PROJECT_ROOT/interop-tests"
    wasm-pack build --target web || {
        echo -e "${RED}Error: Failed to build WASM package${NC}"
        exit 1
    }
fi

# Install Python dependencies if needed
echo -e "${CYAN}Checking Python dependencies...${NC}"
$PYTHON_CMD -c "import aiohttp" 2>/dev/null || {
    echo -e "${YELLOW}Installing aiohttp...${NC}"
    if [ -d "$PYTHON_PROJECT_ROOT/venv" ]; then
        "$PYTHON_PROJECT_ROOT/venv/bin/pip" install aiohttp || {
            echo -e "${RED}Error: Failed to install aiohttp${NC}"
            exit 1
        }
    else
        pip install --break-system-packages aiohttp || {
            echo -e "${RED}Error: Failed to install aiohttp${NC}"
            exit 1
        }
    fi
}

# Clean up old address file
rm -f "$ADDRESS_FILE"

# Start coordinator server
echo -e "${BLUE}Starting coordinator server on port $COORDINATOR_PORT...${NC}"
cd "$SCRIPT_DIR"
$PYTHON_CMD coordinator_server.py --address-file "$ADDRESS_FILE" --port $COORDINATOR_PORT --debug > /tmp/coordinator.log 2>&1 &
COORDINATOR_PID=$!
sleep 2

# Check if coordinator started
if ! kill -0 $COORDINATOR_PID 2>/dev/null; then
    echo -e "${RED}Error: Coordinator server failed to start${NC}"
    cat /tmp/coordinator.log
    exit 1
fi

# Start Python listener
echo -e "${BLUE}Starting Python listener (ws, noise, mplex)...${NC}"
cd "$PYTHON_PROJECT_ROOT"
$PYTHON_CMD "$SCRIPT_DIR/local_ping_listener.py" \
    --transport ws \
    --address-file "$ADDRESS_FILE" \
    --debug > /tmp/python_listener.log 2>&1 &
PYTHON_LISTENER_PID=$!

# Wait for listener to be ready
echo -e "${CYAN}Waiting for Python listener to be ready...${NC}"
for i in {1..30}; do
    if [ -f "$ADDRESS_FILE" ] && [ -s "$ADDRESS_FILE" ]; then
        LISTENER_ADDR=$(cat "$ADDRESS_FILE")
        echo -e "${GREEN}Listener ready at: $LISTENER_ADDR${NC}"
        break
    fi
    sleep 1
done

if [ ! -f "$ADDRESS_FILE" ] || [ ! -s "$ADDRESS_FILE" ]; then
    echo -e "${RED}Error: Listener failed to start or write address${NC}"
    cat /tmp/python_listener.log
    exit 1
fi

# Start Rust chromium dialer
echo -e "${BLUE}Starting Rust chromium dialer (ws, noise, mplex)...${NC}"

# Use local Rust project if available, otherwise fall back to main project
LOCAL_RUST_DIR="$SCRIPT_DIR/rust-local"
if [ -d "$LOCAL_RUST_DIR" ] && [ -f "$LOCAL_RUST_DIR/Cargo.toml" ]; then
    echo -e "${CYAN}Using local Rust project${NC}"
    cd "$LOCAL_RUST_DIR"
    # Set up WASM package symlink
    if [ -f "$LOCAL_RUST_DIR/build.sh" ]; then
        "$LOCAL_RUST_DIR/build.sh" || {
            echo -e "${YELLOW}WASM package setup failed, trying to build...${NC}"
            cd "$RUST_PROJECT_ROOT/interop-tests"
            wasm-pack build --target web 2>&1 | tail -20 || {
                echo -e "${RED}Error: Failed to build WASM package${NC}"
                echo -e "${YELLOW}Note: You may need to fix compilation issues in the Rust project${NC}"
                exit 1
            }
            cd "$LOCAL_RUST_DIR"
            "$LOCAL_RUST_DIR/build.sh" || {
                echo -e "${RED}Error: Failed to set up WASM package${NC}"
                exit 1
            }
        }
    fi
    cd "$LOCAL_RUST_DIR"
else
    echo -e "${CYAN}Using main Rust project${NC}"
    cd "$RUST_PROJECT_ROOT/interop-tests"
fi

# Set environment variables for Rust test
export transport=ws
export security=noise
export muxer=mplex
export ip=0.0.0.0
export is_dialer=true
export test_timeout_seconds=$TEST_TIMEOUT
export redis_addr="127.0.0.1:$COORDINATOR_PORT"
# Enable Rust debug logging
export RUST_LOG=debug

# Run the wasm ping test (this will start chromedriver and browser)
RUST_LOG=debug cargo run --bin wasm_ping > /tmp/rust_dialer.log 2>&1 &
RUST_DIALER_PID=$!

# Wait for test to complete
echo -e "${CYAN}Waiting for test to complete (timeout: ${TEST_TIMEOUT}s)...${NC}"

# Poll for results
RESULT_FILE="/tmp/interop_test_result.json"
for i in $(seq 1 $TEST_TIMEOUT); do
    # Check if Rust dialer is still running
    if ! kill -0 $RUST_DIALER_PID 2>/dev/null; then
        # Process finished, check exit code
        wait $RUST_DIALER_PID
        EXIT_CODE=$?
        if [ $EXIT_CODE -eq 0 ]; then
            echo -e "${GREEN}Test completed successfully!${NC}"
            # Try to get results from coordinator
            sleep 1
            curl -s "http://localhost:$COORDINATOR_PORT/results" > "$RESULT_FILE" 2>/dev/null || true
            if [ -f "$RESULT_FILE" ] && [ -s "$RESULT_FILE" ]; then
                echo -e "${GREEN}Test results:${NC}"
                cat "$RESULT_FILE" | $PYTHON_CMD -m json.tool
            fi
            exit 0
        else
            echo -e "${RED}Test failed with exit code $EXIT_CODE${NC}"
            echo -e "${YELLOW}Python listener logs:${NC}"
            tail -50 /tmp/python_listener.log
            echo -e "${YELLOW}Rust dialer logs:${NC}"
            tail -50 /tmp/rust_dialer.log
            exit 1
        fi
    fi
    sleep 1
done

# Timeout
echo -e "${RED}Test timed out after ${TEST_TIMEOUT} seconds${NC}"
echo -e "${YELLOW}Python listener logs:${NC}"
tail -50 /tmp/python_listener.log
echo -e "${YELLOW}Rust dialer logs:${NC}"
tail -50 /tmp/rust_dialer.log
echo -e "${YELLOW}Coordinator logs:${NC}"
tail -50 /tmp/coordinator.log
exit 1
