import pytest
from httpx import ASGITransport, AsyncClient

from py_ipfs_lite.api import app
from py_ipfs_lite.config import Config
from py_ipfs_lite.peer import Peer


@pytest.fixture
def memory_config():
    return Config(blockstore_type="memory", reprovide_interval_seconds=-1)


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
    from py_ipfs_lite.api import app

    peer = app.state.peer
    await peer.add_node({"msg": "test"}, codec="dag-cbor")

    res = await client.post("/api/v0/repo/stat")
    assert res.status_code == 200
    assert "NumObjects" in res.json()
    assert res.json()["NumObjects"] > 0
    assert res.json()["RepoSize"] > 0


@pytest.mark.trio
async def test_api_swarm_peers(client):
    res = await client.post("/api/v0/swarm/peers")
    assert res.status_code == 200
    assert isinstance(res.json()["Peers"], list)


@pytest.mark.trio
async def test_api_swarm_peers_error_handling(client):
    from unittest.mock import PropertyMock

    from py_ipfs_lite.api import app

    peer = app.state.peer
    network = peer.host.get_network()
    type(network).connections = PropertyMock(side_effect=Exception("mock error"))
    try:
        res = await client.post("/api/v0/swarm/peers")
        assert res.status_code == 500
        assert "mock error" in res.text
    finally:
        del type(network).connections


@pytest.mark.trio
async def test_api_block_stat_missing(client):
    res = await client.post(
        "/api/v0/block/stat?arg=bafkreicwbc3r3ivsekh26gvj7t67zjucmbyelvsqwouyjnghkkmr7f5ynu"
    )
    assert res.status_code == 404


@pytest.mark.trio
async def test_api_lifespan_bootstraps():
    from unittest.mock import AsyncMock

    from py_ipfs_lite.api import app, lifespan
    from py_ipfs_lite.config import Config
    from py_ipfs_lite.peer import Peer

    config = Config(offline=False, use_ipni=False)
    peer = Peer(config, listen_addrs=["/ip4/127.0.0.1/tcp/0"])
    peer.bootstrap = AsyncMock()
    app.state.peer = peer

    async with lifespan(app):
        assert peer.bootstrap.called
        assert len(peer.bootstrap.call_args[0][0]) > 0
    await peer.close()


@pytest.mark.trio
async def test_api_400_for_malformed_input(client):
    # Test bad CID
    res = await client.post("/api/v0/dag/get?arg=not-a-valid-cid")
    assert res.status_code == 400
    assert "not-a-valid-cid" in res.text

    # Test bad JSON body
    res = await client.post("/api/v0/dag/put", content=b"{bad json")
    assert res.status_code == 400


@pytest.mark.trio
async def test_api_400_for_deeply_nested_json(client):
    depth = 100000
    body = "[" * depth + "1" + "]" * depth
    res = await client.post("/api/v0/dag/put", content=body)
    assert res.status_code == 400
    assert "recursion" in res.text.lower()
