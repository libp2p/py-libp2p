#!/usr/bin/env bash
set -e

echo "Demo 7: Background Reprovider Loop"
echo ""
echo "Starting py-ipfs-lite daemon with an accelerated 3-second reprovide interval..."
echo "Configuration: port=0, reprovide-interval=3, blockstore=filesystem"

uv run py-ipfs-lite --debug daemon --port 0 --reprovide-interval 3 \
  --blockstore-type filesystem --blockstore-path ./demo_blocks > reprovider.log 2>&1 &
DAEMON_PID=$!

trap "kill $DAEMON_PID 2>/dev/null || true; rm -f reprovider.log" EXIT

echo "Daemon started! Waiting 10 seconds to allow multiple DHT reprovide loops to run in the background..."
sleep 10

echo ""
echo "Captured Reprovider Logs:"
grep -E "Reproviding.*blocks to the DHT|Finished reproviding" reprovider.log || echo "No reprovide logs found!"

echo ""
echo "Demo 7 finished successfully! Shutting down daemon..."
