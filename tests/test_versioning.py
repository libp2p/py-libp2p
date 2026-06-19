import os
import tempfile
import pytest
from py_ipfs_lite.versioning import init_repo_version, get_repo_version, REPO_VERSION

def test_init_repo_version_creates_file():
    with tempfile.TemporaryDirectory() as temp_dir:
        init_repo_version(temp_dir)
        
        version_file = os.path.join(temp_dir, "version")
        assert os.path.exists(version_file)
        
        with open(version_file, "r") as f:
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

from fastapi.testclient import TestClient
from py_ipfs_lite.api import app

def test_repo_version_endpoint():
    # Setup testclient
    client = TestClient(app)
    # the peer inside lifespan uses memory blockstore by default if config is empty
    response = client.get("/api/v0/repo/version")
    assert response.status_code == 200
    assert response.json()["Version"] == "memory"
