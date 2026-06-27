import pytest
from httpx import ASGITransport, AsyncClient

from py_ipfs_lite.api import app
from py_ipfs_lite.config import Config
from py_ipfs_lite.exceptions import (
    BlockNotFoundError,
    PeerNotStartedError,
    PinNotFoundError,
)
from py_ipfs_lite.peer import Peer


@pytest.fixture
def unstarted_peer():
    config = Config(blockstore_type="memory")
    return Peer(config)


@pytest.mark.trio
async def test_peer_not_started_error(unstarted_peer):
    with pytest.raises(PeerNotStartedError):
        await unstarted_peer.add_node({"hello": "world"})


@pytest.fixture
async def started_peer():
    config = Config(blockstore_type="memory")
    peer = Peer(config, listen_addrs=["/ip4/127.0.0.1/tcp/0"])
    await peer.start()
    try:
        yield peer
    finally:
        await peer.close()


@pytest.mark.trio
async def test_block_not_found_error(started_peer):
    async def mock_get_block(cid):
        return None

    started_peer._exchange.get_block = mock_get_block

    with pytest.raises(BlockNotFoundError):
        await started_peer.get_node("QmYyQSo1c1Ym7orWxLYvCrM2EmxFTANf8wXmmE7DWjhx5N")


@pytest.mark.trio
async def test_pin_not_found_error(started_peer):
    with pytest.raises(PinNotFoundError):
        started_peer.pin_store.remove_pin(
            "QmYyQSo1c1Ym7orWxLYvCrM2EmxFTANf8wXmmE7DWjhx5N"
        )


@pytest.fixture
async def client(started_peer):
    app.state.peer = started_peer
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.trio
async def test_api_404_for_block_not_found(client, started_peer):
    async def mock_get_block(cid):
        return None

    started_peer._exchange.get_block = mock_get_block

    response = await client.post(
        "/api/v0/dag/get?arg=QmYyQSo1c1Ym7orWxLYvCrM2EmxFTANf8wXmmE7DWjhx5N"
    )
    assert response.status_code == 404
    assert "Block not found" in response.json()["detail"]


@pytest.mark.trio
async def test_api_503_for_peer_not_started():
    unstarted = Peer(Config(blockstore_type="memory"))
    app.state.peer = unstarted
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post("/api/v0/dag/put", data=b"{}")
        assert response.status_code == 503
        assert "Peer not started" in response.json()["detail"]
