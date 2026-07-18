export IPFS_LITE_SEED="test_seed_1234567890abcdef123456"

echo "=== Testing Native CLI ==="
uv run py-ipfs-lite daemon > native_output.log 2>&1 &
NATIVE_PID=$!
sleep 5
kill $NATIVE_PID
NATIVE_ID=$(grep "Daemon P2P Peer ID:" native_output.log | tail -1 | awk '{print $NF}')
echo "Native Peer ID: $NATIVE_ID"

echo "=== Testing Docker ==="
docker build -q -t py-ipfs-lite . > /dev/null
docker run --rm -d --name ipfs-test -e IPFS_LITE_SEED=$IPFS_LITE_SEED py-ipfs-lite daemon > /dev/null
sleep 5
DOCKER_ID=$(docker logs ipfs-test 2>&1 | grep "Daemon P2P Peer ID:" | tail -1 | awk '{print $NF}')
docker rm -f ipfs-test > /dev/null
echo "Docker Peer ID: $DOCKER_ID"

echo "=== Result ==="
if [ "$NATIVE_ID" == "$DOCKER_ID" ] && [ ! -z "$NATIVE_ID" ]; then
    echo "SUCCESS! Both environments produced the exact same Peer ID: $NATIVE_ID"
else
    echo "FAILED! Mismatch or missing IDs."
fi
