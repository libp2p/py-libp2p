import os
import tempfile

import pytest

from py_ipfs_lite.versioning import REPO_VERSION, get_repo_version, init_repo_version


def test_init_repo_version_creates_file():
    with tempfile.TemporaryDirectory() as temp_dir:
        init_repo_version(temp_dir)

        version_file = os.path.join(temp_dir, "version")
        assert os.path.exists(version_file)

        with open(version_file) as f:
            content = f.read().strip()

        assert content == REPO_VERSION


def test_get_repo_version():
    with tempfile.TemporaryDirectory() as temp_dir:
        init_repo_version(temp_dir)
        version = get_repo_version(temp_dir)
        assert version == REPO_VERSION


def test_get_repo_version_unknown():
    with tempfile.TemporaryDirectory() as temp_dir:
        version = get_repo_version(temp_dir)
        assert version == "unknown"


def test_init_repo_version_existing_mismatch(caplog):
    with tempfile.TemporaryDirectory() as temp_dir:
        version_file = os.path.join(temp_dir, "version")
        with open(version_file, "w") as f:
            f.write("0")

        init_repo_version(temp_dir)
        assert "Repo version mismatch!" in caplog.text


from httpx import ASGITransport, AsyncClient

from py_ipfs_lite.api import app
from py_ipfs_lite.config import Config
from py_ipfs_lite.peer import Peer


@pytest.fixture
def memory_config():
    return Config(blockstore_type="memory")


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
async def test_repo_version_endpoint(client):
    response = await client.get("/api/v0/repo/version")
    assert response.status_code == 200
    assert response.json()["Version"] == "memory"
