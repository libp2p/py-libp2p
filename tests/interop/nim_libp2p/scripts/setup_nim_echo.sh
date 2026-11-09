#!/usr/bin/env bash
# tests/interop/nim_libp2p/scripts/setup_nim_echo.sh
# Cache-aware setup that skips rebuild if the binary already exists.
# Always installs the pinned nim-libp2p version so CI does not drift on upstream API changes.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${SCRIPT_DIR}/.."

# Pin to a known-good nim-libp2p release (v2 Rng API). Override with NIM_LIBP2P_REF if needed.
NIM_LIBP2P_REF="${NIM_LIBP2P_REF:-#v2.4.2}"

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

main() {
    log_info "Setting up nim echo server for interop testing..."

    # Check if nim is available
    if ! command -v nim &> /dev/null || ! command -v nimble &> /dev/null; then
        log_error "Nim not found. Please install nim first."
        exit 1
    fi

    cd "${PROJECT_DIR}"

    # Create logs directory
    mkdir -p logs

    # Check if binary already exists
    if [[ -f "nim_echo_server" ]]; then
        log_info "nim_echo_server already exists, skipping build"
        return 0
    fi

    # Always install the pinned version so a cached older libp2p cannot break the build
    log_info "Installing nim-libp2p (${NIM_LIBP2P_REF})..."
    nimble install -y "libp2p@${NIM_LIBP2P_REF}"

    log_info "Building nim echo server..."
    # Compile the echo server
    nim c \
        -d:release \
        -d:chronicles_log_level=INFO \
        -d:libp2p_quic_support \
        -d:chronos_event_loop=iocp \
        -d:ssl \
        --opt:speed \
        --mm:orc \
        --verbosity:1 \
        -o:nim_echo_server \
        nim_echo_server.nim

    # Verify binary was created
    if [[ -f "nim_echo_server" ]]; then
        log_info "✅ nim_echo_server built successfully"
        log_info "Binary size: $(ls -lh nim_echo_server | awk '{print $5}')"
    else
        log_error "❌ Failed to build nim_echo_server"
        exit 1
    fi

    log_info "🎉 Setup complete!"
}

main "$@"
