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
