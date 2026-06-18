#!/usr/bin/env bash
set -e

echo "Demo 6: HTTP API Server (Kubo-compatible)"
echo ""
echo "Starting py-ipfs-lite daemon with HTTP API enabled..."
echo "Configuration: port=0 (random P2P port), api-port=8085, blockstore=filesystem"

# We use port 8085 to avoid conflicts if Kubo is already running on 5001
uv run py-ipfs-lite daemon --port 0 --api --api-host 127.0.0.1 --api-port 8085 \
  --blockstore-type filesystem --blockstore-path ./demo_blocks > daemon.log 2>&1 &
DAEMON_PID=$!

# Ensure daemon is killed when the script exits
trap "kill $DAEMON_PID 2>/dev/null || true; rm -f hello.txt daemon.log" EXIT

echo "Waiting for API to initialize on http://127.0.0.1:8085..."
sleep 3

echo ""
echo "1. Adding a standard file via HTTP API (/api/v0/add)"
echo "Writing 'hello from py-ipfs-lite' to hello.txt"
echo "hello from py-ipfs-lite" > hello.txt
echo "Running: curl -s -F file=@hello.txt http://127.0.0.1:8085/api/v0/add"
ADD_RESP=$(curl -s -F file=@hello.txt http://127.0.0.1:8085/api/v0/add)
echo "Server Response: $ADD_RESP"
# Extract the Hash field from the JSON response
FILE_CID=$(echo $ADD_RESP | grep -o '"Hash":"[^"]*' | grep -o '[^"]*$')
echo "Extracted CID: $FILE_CID"

echo ""
echo "2. Fetching the file back via HTTP API (/api/v0/cat)"
echo "Running: curl -s \"http://127.0.0.1:8085/api/v0/cat?arg=$FILE_CID\""
echo "Content fetched:"
curl -s "http://127.0.0.1:8085/api/v0/cat?arg=$FILE_CID"
echo ""

echo ""
echo "3. Storing a structured DAG-JSON node via HTTP API (/api/v0/dag/put)"
echo "Payload: {\"hello\":\"world\"}"
echo "Running: curl -s -X POST -H \"Content-Type: application/json\" -d '{\"hello\":\"world\"}' \"http://127.0.0.1:8085/api/v0/dag/put?store-codec=dag-json\""
DAG_PUT_RESP=$(curl -s -X POST -H "Content-Type: application/json" \
  -d '{"hello":"world"}' \
  "http://127.0.0.1:8085/api/v0/dag/put?store-codec=dag-json")
echo "Server Response: $DAG_PUT_RESP"
# Extract the CID from the nested Cid object
DAG_CID=$(echo $DAG_PUT_RESP | grep -o '"Cid":{"/":"[^"]*' | grep -o '[^"]*$')
echo "Extracted DAG CID: $DAG_CID"

echo ""
echo "4. Fetching the DAG node back via HTTP API (/api/v0/dag/get)"
echo "Running: curl -s \"http://127.0.0.1:8085/api/v0/dag/get?arg=$DAG_CID\""
echo "Content fetched:"
curl -s "http://127.0.0.1:8085/api/v0/dag/get?arg=$DAG_CID"
echo ""

echo ""
echo "5. Pinning the node & running Garbage Collection via HTTP API"
echo "Running: curl -s -X POST \"http://127.0.0.1:8085/api/v0/pin/add?arg=$DAG_CID&recursive=true\""
curl -s -X POST "http://127.0.0.1:8085/api/v0/pin/add?arg=$DAG_CID&recursive=true"
echo ""
echo "Triggering GC to clear unpinned blocks..."
echo "Running: curl -s -X POST \"http://127.0.0.1:8085/api/v0/repo/gc\""
curl -s -X POST "http://127.0.0.1:8085/api/v0/repo/gc"
echo ""

echo ""
echo "Demo 6 finished successfully! Shutting down daemon..."
