import pytest
from fastapi.testclient import TestClient

from py_ipfs_lite.api import app


@pytest.fixture
def client():
    return TestClient(app)


def test_metrics_endpoint(client):
    from unittest.mock import Mock

    mock_peer = Mock()
    mock_network = Mock()
    mock_network.connections = {}
    mock_peer.host.get_network.return_value = mock_network
    app.state.peer = mock_peer
    response = client.get("/debug/metrics/prometheus")
    assert response.status_code == 200
    content = response.text

    assert "ipfs_blockstore_blocks_total" in content
    assert "ipfs_gc_runs_total" in content
    assert "ipfs_dht_query_latency_seconds" in content
    assert "ipfs_bitswap_bytes_received_total" in content
    assert "ipfs_swarm_peers" in content


@pytest.mark.trio
async def test_metrics_idempotent_put():
    from py_ipfs_lite.config import Config
    from py_ipfs_lite.metrics import IPFS_BLOCKSTORE_BLOCKS_TOTAL
    from py_ipfs_lite.peer import Peer

    before_count = IPFS_BLOCKSTORE_BLOCKS_TOTAL._value.get()

    config = Config(offline=True, blockstore_type="memory")
    async with Peer(config, listen_addrs=["/ip4/127.0.0.1/tcp/0"]) as peer:
        # Add the same file twice
        await peer.add_file(b"idempotent content test")
        await peer.add_file(b"idempotent content test")

    after_count = IPFS_BLOCKSTORE_BLOCKS_TOTAL._value.get()
    # Adding a file adds exactly 1 block in this case, but adding it twice should still be just 1 block added.
    assert after_count == before_count + 1
