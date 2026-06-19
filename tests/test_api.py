import pytest
from httpx import AsyncClient, ASGITransport
import trio
from py_ipfs_lite.api import app

from py_ipfs_lite.peer import Peer
from py_ipfs_lite.config import Config

@pytest.fixture
def memory_config():
    return Config(
        blockstore_type="memory",
        reprovide_interval_seconds=-1
    )

@pytest.fixture
async def client(memory_config):
    peer = Peer(memory_config, listen_addrs=["/ip4/127.0.0.1/tcp/0"])
    await peer.start()
    try:
        app.state.peer = peer
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        await peer.close()

@pytest.mark.trio
async def test_api_version(client):
    res = await client.post("/api/v0/version")
    assert res.status_code == 200
    assert res.json()["System"] == "py-ipfs-lite"

@pytest.mark.trio
async def test_api_id(client):
    res = await client.post("/api/v0/id")
    assert res.status_code == 200
    assert "ID" in res.json()

@pytest.mark.trio
async def test_api_repo_stat(client):
    res = await client.post("/api/v0/repo/stat")
    assert res.status_code == 200
    assert "NumObjects" in res.json()

@pytest.mark.trio
async def test_api_swarm_peers(client):
    res = await client.post("/api/v0/swarm/peers")
    assert res.status_code == 200
    assert isinstance(res.json()["Peers"], list)
