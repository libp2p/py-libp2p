import pytest
from fastapi.testclient import TestClient
from py_ipfs_lite.api import app

@pytest.fixture
def client():
    return TestClient(app)

def test_metrics_endpoint(client):
    response = client.get("/debug/metrics/prometheus")
    assert response.status_code == 200
    content = response.text
    
    assert "ipfs_blockstore_blocks_total" in content
    assert "ipfs_gc_runs_total" in content
    assert "ipfs_dht_query_latency_seconds" in content
    assert "ipfs_bitswap_bytes_received_total" in content
