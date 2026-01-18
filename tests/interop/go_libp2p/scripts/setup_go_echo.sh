#!/usr/bin/env bash
# tests/interop/go_libp2p/scripts/setup_go_echo.sh
# Build go echo server for interop testing

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${SCRIPT_DIR}/.."

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

main() {
    log_info "Setting up go echo server for interop testing..."

    # Check if go is available
    if ! command -v go &> /dev/null; then
        log_error "Go not found. Please install Go first."
        exit 1
    fi

    # Check Go version
    GO_VERSION=$(go version | awk '{print $3}' | sed 's/go//')
    log_info "Found Go version: ${GO_VERSION}"

    cd "${PROJECT_DIR}"

    # Create logs directory
    mkdir -p logs

    # Check if binary already exists
    if [[ -f "go_echo_server" ]]; then
        log_info "go_echo_server already exists, skipping build"
        return 0
    fi

    log_info "Downloading dependencies..."
    go mod tidy

    log_info "Building go echo server..."
    CGO_ENABLED=0 go build -o go_echo_server go_echo_server.go

    # Verify binary was created
    if [[ -f "go_echo_server" ]]; then
        log_info "go_echo_server built successfully"
        log_info "Binary size: $(ls -lh go_echo_server | awk '{print $5}')"
    else
        log_error "Failed to build go_echo_server"
        exit 1
    fi

    log_info "Setup complete!"
}

main "$@"
