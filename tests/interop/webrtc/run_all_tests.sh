#!/bin/bash

################################################################################
# Master WebRTC Interop Test Suite - FIXED VERSION
# Runs all interop tests in one command
# Supports: Python, Go, Rust, JavaScript
################################################################################

set -e

# ============================================================================
# Configuration
# ============================================================================

REDIS_HOST="localhost"
REDIS_PORT="6379"
TEST_TIMEOUT=45
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
REPORT_FILE="$SCRIPT_DIR/interop_test_report_${TIMESTAMP}.md"
LOG_DIR="/tmp/webrtc_interop_${TIMESTAMP}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Counters
TOTAL_TESTS=0
PASSED_TESTS=0
FAILED_TESTS=0

# PIDs
declare -a PIDS

# ============================================================================
# Logging Functions
# ============================================================================

log() {
    echo -e "${BLUE}[INFO]${NC} $1" | tee -a "$REPORT_FILE"
}

success() {
    echo -e "${GREEN}[✓]${NC} $1" | tee -a "$REPORT_FILE"
}

error() {
    echo -e "${RED}[✗]${NC} $1" | tee -a "$REPORT_FILE"
}

warning() {
    echo -e "${YELLOW}[!]${NC} $1" | tee -a "$REPORT_FILE"
}

section() {
    echo "" | tee -a "$REPORT_FILE"
    echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}" | tee -a "$REPORT_FILE"
    echo -e "${BLUE}  $1${NC}" | tee -a "$REPORT_FILE"
    echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}" | tee -a "$REPORT_FILE"
    echo "" | tee -a "$REPORT_FILE"
}

test_header() {
    echo "" | tee -a "$REPORT_FILE"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}" | tee -a "$REPORT_FILE"
    echo -e "${CYAN}  TEST: $1${NC}" | tee -a "$REPORT_FILE"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}" | tee -a "$REPORT_FILE"
    echo "" | tee -a "$REPORT_FILE"
}

# ============================================================================
# Initialization
# ============================================================================

initialize() {
    mkdir -p "$LOG_DIR"
    touch "$REPORT_FILE"

    cat > "$REPORT_FILE" << EOF
# WebRTC Interop Test Report
Generated: $(date)
Timestamp: $TIMESTAMP

---

EOF

    log "Log directory: $LOG_DIR"
    log "Report file: $REPORT_FILE"
}

# ============================================================================
# Cleanup Function (CRITICAL)
# ============================================================================

cleanup() {
    log "Cleaning up..."

    # Kill all tracked processes
    for pid in "${PIDS[@]}"; do
        if kill -0 $pid 2>/dev/null; then
            log "Killing process $pid..."
            kill $pid 2>/dev/null || true
        fi
    done

    # Wait a bit
    sleep 1

    # Force kill any remaining Python/Go processes
    pkill -f py_listener 2>/dev/null || true
    pkill -f py_dialer 2>/dev/null || true
    pkill -f "go_peer" 2>/dev/null || true

    # Clear Redis
    redis-cli FLUSHALL 2>/dev/null || true

    success "Cleanup complete"
}

trap cleanup EXIT

# ============================================================================
# Helper Functions
# ============================================================================

wait_for_redis_key() {
    local key=$1
    local timeout=$2
    local start=$(date +%s)

    while true; do
        local current=$(date +%s)
        local elapsed=$((current - start))

        if [ $elapsed -gt $timeout ]; then
            return 1
        fi

        local value=$(redis-cli GET "$key" 2>/dev/null || echo "")
        if [ -n "$value" ]; then
            return 0
        fi

        sleep 0.2
    done
}

# ============================================================================
# Pre-flight Checks
# ============================================================================

check_redis() {
    if ! redis-cli -h $REDIS_HOST -p $REDIS_PORT ping > /dev/null 2>&1; then
        error "Redis not running at $REDIS_HOST:$REDIS_PORT"
        return 1
    fi
    success "Redis running"
    return 0
}

check_python() {
    if ! command -v python3 &> /dev/null; then
        error "python3 not found"
        return 1
    fi
    success "python3 found"

    # Check for venv or system packages
    if [ -d "$SCRIPT_DIR/venv" ]; then
        source "$SCRIPT_DIR/venv/bin/activate"
        log "Using virtual environment at $SCRIPT_DIR/venv"
    fi

    if ! python3 -c "import redis, aiortc" 2>/dev/null; then
        error "Missing Python packages (redis, aiortc)"
        warning "Run: python3 -m venv venv && source venv/bin/activate && pip install redis aiortc"
        return 1
    fi
    success "Python packages OK"
    return 0
}

check_go() {
    if ! command -v go &> /dev/null; then
        warning "go not found"
        return 1
    fi
    success "go found"
    return 0
}

check_rust() {
    if ! command -v cargo &> /dev/null; then
        warning "cargo not found"
        return 1
    fi
    success "cargo found"
    return 0
}

check_node() {
    if ! command -v node &> /dev/null; then
        warning "node not found"
        return 1
    fi
    success "node found"

    if ! command -v npm &> /dev/null; then
        warning "npm not found"
        return 1
    fi
    success "npm found"
    return 0
}

preflight_checks() {
    section "Pre-flight Checks"

    check_redis || exit 1
    check_python || exit 1

    GO_AVAILABLE=1
    check_go || GO_AVAILABLE=0

    RUST_AVAILABLE=1
    check_rust || RUST_AVAILABLE=0

    NODE_AVAILABLE=1
    check_node || NODE_AVAILABLE=0

    success "All critical dependencies OK"
}

# ============================================================================
# Build Functions
# ============================================================================

build_go_peer() {
    log "Building Go peer..."
    if [ ! -f "$SCRIPT_DIR/go_peer.go" ]; then
        error "go_peer.go not found"
        return 1
    fi

    if ! go build -o "$SCRIPT_DIR/go_peer" "$SCRIPT_DIR/go_peer.go" 2>&1; then
        error "Failed to build Go peer"
        return 1
    fi

    success "Go peer built"
    return 0
}

build_rust_peer() {
    if [ ! -f "$SCRIPT_DIR/Cargo.toml" ]; then
        warning "Cargo.toml not found"
        return 1
    fi

    if [ ! -f "$SCRIPT_DIR/rs_peer.rs" ]; then
        warning "rs_peer.rs not found"
        return 1
    fi

    # Create src directory if it doesn't exist
    mkdir -p "$SCRIPT_DIR/src"
    cp "$SCRIPT_DIR/rs_peer.rs" "$SCRIPT_DIR/src/main.rs"

    log "Building Rust peer..."
    if ! cargo build --release --manifest-path "$SCRIPT_DIR/Cargo.toml" 2>&1 > "$LOG_DIR/cargo_build.log"; then
        error "Failed to build Rust peer (check $LOG_DIR/cargo_build.log)"
        return 1
    fi

    success "Rust peer built"
    return 0
}

install_node_deps() {
    if [ ! -f "$SCRIPT_DIR/package.json" ]; then
        warning "package.json not found"
        return 1
    fi

    log "Installing Node dependencies..."
    if ! npm install --prefix "$SCRIPT_DIR" 2>&1 > "$LOG_DIR/npm_install.log"; then
        error "Failed to install Node dependencies"
        return 1
    fi

    success "Node dependencies installed"
    return 0
}

build_all() {
    section "Building All Peers"

    if [ "$GO_AVAILABLE" = "1" ]; then
        build_go_peer || true
    fi

    if [ "$RUST_AVAILABLE" = "1" ]; then
        build_rust_peer || true
    fi

    if [ "$NODE_AVAILABLE" = "1" ]; then
        install_node_deps || true
    fi
}

# ============================================================================
# Test Functions
# ============================================================================

run_test_py_go() {
    test_header "Python Listener ↔ Go Dialer"
    TOTAL_TESTS=$((TOTAL_TESTS + 1))

    # Clear Redis
    redis-cli FLUSHALL 2>/dev/null || true
    sleep 1

    # Activate venv if available
    if [ -d "$SCRIPT_DIR/venv" ]; then
        PYTHON_CMD="$SCRIPT_DIR/venv/bin/python3"
    else
        PYTHON_CMD="python3"
    fi

    # Start Python listener
    log "Starting Python listener..."
    $PYTHON_CMD "$SCRIPT_DIR/py_listener.py" > "$LOG_DIR/py_listener.log" 2>&1 &
    PY_PID=$!
    PIDS+=($PY_PID)
    sleep 4

    # Check if listener is ready
    if ! wait_for_redis_key "interop:webrtc:listener:ready" 10; then
        error "Python listener failed to start"
        kill $PY_PID 2>/dev/null || true
        FAILED_TESTS=$((FAILED_TESTS + 1))
        return 1
    fi

    log "Python listener ready"

    # Start Go dialer (no need for separate Go listener in this test)
    log "Starting Go dialer..."
    "$SCRIPT_DIR/go_peer" dialer > "$LOG_DIR/go_dialer.log" 2>&1 &
    GO_DIALER_PID=$!
    PIDS+=($GO_DIALER_PID)

    # Wait for Go dialer to connect and signal
    log "Waiting for Go dialer to connect..."
    if wait_for_redis_key "interop:webrtc:dialer:connected" 30; then
        if wait_for_redis_key "interop:webrtc:ping:success" 10; then
            success "TEST PASSED: Python ↔ Go"
            PASSED_TESTS=$((PASSED_TESTS + 1))

            # Clean up processes
            kill $PY_PID $GO_DIALER_PID 2>/dev/null || true
            sleep 1
            return 0
        fi
    fi

    error "TEST FAILED: Python ↔ Go"
    FAILED_TESTS=$((FAILED_TESTS + 1))

    log "Python listener log (last 30 lines):"
    tail -30 "$LOG_DIR/py_listener.log" | sed 's/^/  /'

    log "Go dialer log (last 30 lines):"
    tail -30 "$LOG_DIR/go_dialer.log" | sed 's/^/  /'

    return 1
}

run_test_go_py() {
    test_header "Go Listener ↔ Python Dialer"
    TOTAL_TESTS=$((TOTAL_TESTS + 1))

    # Clear Redis
    redis-cli FLUSHALL 2>/dev/null || true
    sleep 1

    # Start Go listener
    log "Starting Go listener..."
    "$SCRIPT_DIR/go_peer" listener > "$LOG_DIR/go_listener_alt.log" 2>&1 &
    GO_LISTENER_PID=$!
    PIDS+=($GO_LISTENER_PID)
    sleep 4

    # Check if Go listener is ready
    if ! wait_for_redis_key "interop:webrtc:go:listener:ready" 10; then
        error "Go listener failed to start"
        kill $GO_LISTENER_PID 2>/dev/null || true
        FAILED_TESTS=$((FAILED_TESTS + 1))
        return 1
    fi

    log "Go listener ready"

    # Activate venv if available
    if [ -d "$SCRIPT_DIR/venv" ]; then
        PYTHON_CMD="$SCRIPT_DIR/venv/bin/python3"
    else
        PYTHON_CMD="python3"
    fi

    # Start Python dialer
    log "Starting Python dialer..."
    $PYTHON_CMD "$SCRIPT_DIR/py_dialer.py" > "$LOG_DIR/py_dialer.log" 2>&1 &
    PY_DIALER_PID=$!
    PIDS+=($PY_DIALER_PID)
    sleep 3

    # Wait for connection
    log "Waiting for Python dialer to connect..."
    if wait_for_redis_key "interop:webrtc:dialer:connected" 30; then
        if wait_for_redis_key "interop:webrtc:ping:success" 10; then
            success "TEST PASSED: Go ↔ Python"
            PASSED_TESTS=$((PASSED_TESTS + 1))

            # Clean up processes
            kill $GO_LISTENER_PID $PY_DIALER_PID 2>/dev/null || true
            sleep 1
            return 0
        fi
    fi

    error "TEST FAILED: Go ↔ Python (timeout)"
    FAILED_TESTS=$((FAILED_TESTS + 1))
    return 1
}

run_test_py_rust() {
    test_header "Python Listener ↔ Rust Dialer"
    TOTAL_TESTS=$((TOTAL_TESTS + 1))

    if [ ! -f "$SCRIPT_DIR/target/release/libp2p-webrtc-interop" ]; then
        warning "Rust binary not found (skipping)"
        return 0
    fi

    redis-cli FLUSHALL 2>/dev/null || true
    sleep 1

    # Activate venv if available
    if [ -d "$SCRIPT_DIR/venv" ]; then
        PYTHON_CMD="$SCRIPT_DIR/venv/bin/python3"
    else
        PYTHON_CMD="python3"
    fi

    log "Starting Python listener..."
    $PYTHON_CMD "$SCRIPT_DIR/py_listener.py" > "$LOG_DIR/py_listener_rust.log" 2>&1 &
    PY_PID=$!
    PIDS+=($PY_PID)
    sleep 4

    if ! wait_for_redis_key "interop:webrtc:listener:ready" 10; then
        error "Python listener failed"
        kill $PY_PID 2>/dev/null || true
        FAILED_TESTS=$((FAILED_TESTS + 1))
        return 1
    fi

    log "Starting Rust dialer..."
    "$SCRIPT_DIR/target/release/libp2p-webrtc-interop" dialer > "$LOG_DIR/rs_dialer.log" 2>&1 &
    RS_DIALER_PID=$!
    PIDS+=($RS_DIALER_PID)
    sleep 3

    if wait_for_redis_key "interop:webrtc:dialer:connected" 30; then
        success "TEST PASSED: Python ↔ Rust"
        PASSED_TESTS=$((PASSED_TESTS + 1))
        return 0
    fi

    error "TEST FAILED: Python ↔ Rust (timeout)"
    FAILED_TESTS=$((FAILED_TESTS + 1))
    return 1
}

run_test_py_node() {
    test_header "Python Listener ↔ JavaScript Dialer"
    TOTAL_TESTS=$((TOTAL_TESTS + 1))

    if [ ! -f "$SCRIPT_DIR/js_peer.js" ]; then
        warning "js_peer.js not found (skipping)"
        return 0
    fi

    redis-cli FLUSHALL 2>/dev/null || true
    sleep 1

    # Activate venv if available
    if [ -d "$SCRIPT_DIR/venv" ]; then
        PYTHON_CMD="$SCRIPT_DIR/venv/bin/python3"
    else
        PYTHON_CMD="python3"
    fi

    log "Starting Python listener..."
    $PYTHON_CMD "$SCRIPT_DIR/py_listener.py" > "$LOG_DIR/py_listener_js.log" 2>&1 &
    PY_PID=$!
    PIDS+=($PY_PID)
    sleep 4

    if ! wait_for_redis_key "interop:webrtc:listener:ready" 10; then
        error "Python listener failed"
        kill $PY_PID 2>/dev/null || true
        FAILED_TESTS=$((FAILED_TESTS + 1))
        return 1
    fi

    log "Starting JavaScript dialer..."
    (cd "$SCRIPT_DIR" && node js_peer.js dialer) > "$LOG_DIR/js_dialer.log" 2>&1 &
    JS_DIALER_PID=$!
    PIDS+=($JS_DIALER_PID)
    sleep 3

    if wait_for_redis_key "interop:webrtc:dialer:connected" 30; then
        if wait_for_redis_key "interop:webrtc:ping:success" 10; then
            success "TEST PASSED: Python ↔ JavaScript"
            PASSED_TESTS=$((PASSED_TESTS + 1))

            # Clean up processes
            kill $PY_PID $JS_DIALER_PID 2>/dev/null || true
            sleep 1
            return 0
        fi
    fi

    error "TEST FAILED: Python ↔ JavaScript (timeout)"
    FAILED_TESTS=$((FAILED_TESTS + 1))
    return 1
}

run_test_node_py() {
    test_header "JavaScript Listener ↔ Python Dialer"
    TOTAL_TESTS=$((TOTAL_TESTS + 1))

    if [ ! -f "$SCRIPT_DIR/js_peer.js" ]; then
        warning "js_peer.js not found (skipping)"
        return 0
    fi

    redis-cli FLUSHALL 2>/dev/null || true
    sleep 1

    # Start JavaScript listener
    log "Starting JavaScript listener..."
    (cd "$SCRIPT_DIR" && node js_peer.js listener) > "$LOG_DIR/js_listener.log" 2>&1 &
    JS_LISTENER_PID=$!
    PIDS+=($JS_LISTENER_PID)
    sleep 4

    # Check if JS listener is ready
    if ! wait_for_redis_key "interop:webrtc:js:listener:ready" 10; then
        error "JavaScript listener failed to start"
        kill $JS_LISTENER_PID 2>/dev/null || true
        FAILED_TESTS=$((FAILED_TESTS + 1))
        return 1
    fi

    log "JavaScript listener ready"

    # Activate venv if available
    if [ -d "$SCRIPT_DIR/venv" ]; then
        PYTHON_CMD="$SCRIPT_DIR/venv/bin/python3"
    else
        PYTHON_CMD="python3"
    fi

    # Start Python dialer
    log "Starting Python dialer..."
    $PYTHON_CMD "$SCRIPT_DIR/py_dialer.py" > "$LOG_DIR/py_dialer_js.log" 2>&1 &
    PY_DIALER_PID=$!
    PIDS+=($PY_DIALER_PID)

    # Wait for connection
    log "Waiting for Python dialer to connect..."
    if wait_for_redis_key "interop:webrtc:dialer:connected" 30; then
        if wait_for_redis_key "interop:webrtc:ping:success" 10; then
            success "TEST PASSED: JavaScript ↔ Python"
            PASSED_TESTS=$((PASSED_TESTS + 1))

            # Clean up processes
            kill $JS_LISTENER_PID $PY_DIALER_PID 2>/dev/null || true
            sleep 1
            return 0
        fi
    fi

    error "TEST FAILED: JavaScript ↔ Python (timeout)"
    FAILED_TESTS=$((FAILED_TESTS + 1))
    return 1
}

run_test_rust_py() {
    test_header "Rust Listener ↔ Python Dialer"
    TOTAL_TESTS=$((TOTAL_TESTS + 1))

    if [ ! -f "$SCRIPT_DIR/target/release/libp2p-webrtc-interop" ]; then
        warning "Rust binary not found (skipping)"
        return 0
    fi

    redis-cli FLUSHALL 2>/dev/null || true
    sleep 1

    log "Starting Rust listener..."
    "$SCRIPT_DIR/target/release/libp2p-webrtc-interop" listener > "$LOG_DIR/rs_listener.log" 2>&1 &
    RS_LISTENER_PID=$!
    PIDS+=($RS_LISTENER_PID)
    sleep 4

    if ! wait_for_redis_key "interop:webrtc:rs:listener:ready" 10; then
        error "Rust listener failed"
        kill $RS_LISTENER_PID 2>/dev/null || true
        FAILED_TESTS=$((FAILED_TESTS + 1))
        return 1
    fi

    log "Rust listener ready"

    # Activate venv if available
    if [ -d "$SCRIPT_DIR/venv" ]; then
        PYTHON_CMD="$SCRIPT_DIR/venv/bin/python3"
    else
        PYTHON_CMD="python3"
    fi

    log "Starting Python dialer..."
    $PYTHON_CMD "$SCRIPT_DIR/py_dialer.py" > "$LOG_DIR/py_dialer_rust.log" 2>&1 &
    PY_DIALER_PID=$!
    PIDS+=($PY_DIALER_PID)

    if wait_for_redis_key "interop:webrtc:dialer:connected" 30; then
        if wait_for_redis_key "interop:webrtc:ping:success" 10; then
            success "TEST PASSED: Rust ↔ Python"
            PASSED_TESTS=$((PASSED_TESTS + 1))

            # Clean up processes
            kill $RS_LISTENER_PID $PY_DIALER_PID 2>/dev/null || true
            sleep 1
            return 0
        fi
    fi

    error "TEST FAILED: Rust ↔ Python (timeout)"
    FAILED_TESTS=$((FAILED_TESTS + 1))
    return 1
}

# ============================================================================
# Report Generation
# ============================================================================

generate_report() {
    section "Test Summary"

    echo "" >> "$REPORT_FILE"
    echo "## Summary" >> "$REPORT_FILE"
    echo "" >> "$REPORT_FILE"
    echo "- Total Tests: $TOTAL_TESTS" >> "$REPORT_FILE"
    echo "- Passed: $PASSED_TESTS ✓" >> "$REPORT_FILE"
    echo "- Failed: $FAILED_TESTS ✗" >> "$REPORT_FILE"
    echo "" >> "$REPORT_FILE"

    if [ "$FAILED_TESTS" -eq 0 ] && [ "$TOTAL_TESTS" -gt 0 ]; then
        echo "✓ ALL TESTS PASSED!" >> "$REPORT_FILE"
        success "ALL TESTS PASSED!"
        return 0
    else
        echo "✗ Some tests failed or no tests ran" >> "$REPORT_FILE"
        error "Tests failed or no tests ran"
        return 1
    fi
}

# ============================================================================
# Main Execution
# ============================================================================

main() {
    section "WebRTC Interop Test Suite"

    initialize
    preflight_checks
    build_all

    section "Running Tests"

    # Python ↔ Go (bidirectional)
    run_test_py_go
    run_test_go_py

    # Python ↔ JavaScript (bidirectional)
    if [ "$NODE_AVAILABLE" = "1" ]; then
        run_test_py_node || true
        run_test_node_py || true
    fi

    # Python ↔ Rust (bidirectional)
    if [ "$RUST_AVAILABLE" = "1" ]; then
        run_test_py_rust || true
        run_test_rust_py || true
    fi

    generate_report

    if [ "$FAILED_TESTS" -eq 0 ] && [ "$TOTAL_TESTS" -gt 0 ]; then
        exit 0
    else
        exit 1
    fi
}

main "$@"
