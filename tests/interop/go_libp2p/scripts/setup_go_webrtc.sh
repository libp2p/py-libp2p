#!/usr/bin/env bash
# Build the go-libp2p WebRTC-Direct interop harness. Skipped by the tests when
# `go` is unavailable; safe to run by hand to prime the binary.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
src="$here/webrtc_direct"
out="$src/go_webrtc_harness"

if ! command -v go >/dev/null 2>&1; then
    echo "go not found; skipping harness build" >&2
    exit 0
fi

cd "$src"
go build -o "$out" .
echo "built $out"
