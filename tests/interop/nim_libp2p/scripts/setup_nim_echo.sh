#!/usr/bin/env bash
# Simple setup script for nim echo server interop testing

set -euo pipefail

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${SCRIPT_DIR}/.."
NIM_LIBP2P_DIR="${PROJECT_ROOT}/nim-libp2p"

# Check prerequisites
check_nim() {
    if ! command -v nim &> /dev/null; then
        log_error "Nim not found. Install with: curl -sSf https://nim-lang.org/choosenim/init.sh | sh"
        exit 1
    fi
    if ! command -v nimble &> /dev/null; then
        log_error "Nimble not found. Please install Nim properly."
        exit 1
    fi
}

# Setup nim-libp2p dependency
setup_nim_libp2p() {
    log_info "Setting up nim-libp2p dependency..."

    if [ ! -d "${NIM_LIBP2P_DIR}" ]; then
        log_info "Cloning nim-libp2p..."
        git clone https://github.com/status-im/nim-libp2p.git "${NIM_LIBP2P_DIR}"
    fi

    cd "${NIM_LIBP2P_DIR}"
    log_info "Installing nim-libp2p dependencies..."
    nimble install -y --depsOnly
}

# Build nim echo server
build_echo_server() {
    log_info "Building nim echo server..."

    cd "${PROJECT_ROOT}"

    # Create nimble file if it doesn't exist
    cat > nim_echo_test.nimble << 'EOF'
# Package
version = "0.1.0"
author = "py-libp2p interop"
description = "nim echo server for interop testing"
license = "MIT"

# Dependencies
requires "nim >= 1.6.0"
requires "libp2p"
requires "chronos"
requires "stew"

# Binary
bin = @["nim_echo_server"]
EOF

    # Build the server
    log_info "Compiling nim echo server..."
    nim c -d:release -d:chronicles_log_level=INFO -d:libp2p_quic_support --opt:speed --gc:orc -o:nim_echo_server nim_echo_server.nim

    if [ -f "nim_echo_server" ]; then
        log_info "✅ nim_echo_server built successfully"
    else
        log_error "❌ Failed to build nim_echo_server"
        exit 1
    fi
}

main() {
    log_info "Setting up nim echo server for interop testing..."

    # Create logs directory
    mkdir -p "${PROJECT_ROOT}/logs"

    # Clean up any existing processes
    pkill -f "nim_echo_server" || true

    check_nim
    setup_nim_libp2p
    build_echo_server

    log_info "🎉 Setup complete! You can now run: python -m pytest test_echo_interop.py -v"
}

main "$@"
