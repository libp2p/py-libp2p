#!/bin/bash
# Build script that sets up WASM package symlink

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUST_PROJECT_ROOT="${RUST_PROJECT_ROOT:-$HOME/PNL_Launchpad_Curriculum/Libp2p/rust-libp2p}"

# Create pkg directory if it doesn't exist
mkdir -p "$SCRIPT_DIR/pkg"

# Check if WASM package exists in main project
if [ -d "$RUST_PROJECT_ROOT/interop-tests/pkg" ]; then
    echo "Linking WASM package from main project..."
    # Remove old symlinks/files
    rm -f "$SCRIPT_DIR/pkg"/*
    # Create symlinks to WASM files
    for file in "$RUST_PROJECT_ROOT/interop-tests/pkg"/*; do
        if [ -f "$file" ]; then
            ln -sf "$file" "$SCRIPT_DIR/pkg/$(basename "$file")"
        fi
    done
    echo "WASM package linked successfully"
else
    echo "WARNING: WASM package not found at $RUST_PROJECT_ROOT/interop-tests/pkg"
    echo "You may need to build it first:"
    echo "  cd $RUST_PROJECT_ROOT/interop-tests"
    echo "  wasm-pack build --target web"
    exit 1
fi
