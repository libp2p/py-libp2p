"""
Tests for p2p_checkpoint.ipfs_utils.

The real :class:`IPFSClient` is tested against a stubbed ``requests``
session (no live Kubo daemon required for CI). If a real daemon happens to
be reachable at the default address, one extra end-to-end test exercises it
too; that test skips itself otherwise.
"""

from __future__ import annotations

import json

import pytest
import requests

from p2p_checkpoint.ipfs_utils import (
    IPFSClient,
    IPFSError,
    IPFSNotFoundError,
    IPFSUnavailableError,
)
from tests.fake_ipfs import FakeIPFS


class _FakeResponse:
    def __init__(self, status_code=200, text="", json_data=None, content=b""):
        self.status_code = status_code
        self.text = text
        self._json = json_data
        self._content = content
        self.ok = 200 <= status_code < 400

    def json(self):
        return self._json

    def iter_content(self, chunk_size=1024):
        for i in range(0, len(self._content), chunk_size):
            yield self._content[i : i + chunk_size]


class _FakeSession:
    """Stand-in for requests.Session that simulates a Kubo daemon storing
    files in memory, keyed by a fake incrementing hash."""

    def __init__(self):
        self.store: dict[str, bytes] = {}
        self._next_id = 0
        self.raise_connection_error = False
        self.raise_timeout = False

    def post(self, url, params=None, files=None, timeout=None, stream=False):
        if self.raise_connection_error:
            raise requests.exceptions.ConnectionError("simulated: connection refused")
        if self.raise_timeout:
            raise requests.exceptions.Timeout("simulated: timed out")

        if url.endswith("/id"):
            return _FakeResponse(200, json_data={"ID": "fake-daemon"})
        if url.endswith("/version"):
            return _FakeResponse(200, json_data={"Version": "0.99.0-fake"})

        if url.endswith("/add"):
            _, (name, fh) = next(iter(files.items()))
            data = fh.read()
            cid = f"Qmfake{self._next_id:040d}"
            self._next_id += 1
            self.store[cid] = data
            return _FakeResponse(200, text=json.dumps({"Name": name, "Hash": cid}))

        if url.endswith("/cat"):
            cid = params["arg"]
            if cid not in self.store:
                return _FakeResponse(404, text="not found")
            return _FakeResponse(200, content=self.store[cid])

        raise AssertionError(f"Unexpected URL in fake session: {url}")


@pytest.fixture()
def fake_session():
    return _FakeSession()


@pytest.fixture()
def client(fake_session):
    return IPFSClient(session=fake_session)


def test_is_available_true(client):
    assert client.is_available() is True


def test_is_available_false_on_connection_error(client, fake_session):
    fake_session.raise_connection_error = True
    assert client.is_available() is False


def test_version(client):
    assert client.version() == "0.99.0-fake"


def test_file_uploaded_and_cid_returned(client, tmp_path):
    f = tmp_path / "checkpoint.tar.gz"
    f.write_bytes(b"fake checkpoint bytes")
    cid = client.upload_file(f)
    assert cid.startswith("Qmfake")


def test_cid_downloaded_matches_original(client, tmp_path):
    f = tmp_path / "checkpoint.tar.gz"
    original = b"fake checkpoint bytes, potentially large" * 100
    f.write_bytes(original)
    cid = client.upload_file(f)

    dest = tmp_path / "downloaded.tar.gz"
    client.download_file(cid, dest)
    assert dest.read_bytes() == original


def test_get_bytes_matches_upload(client, tmp_path):
    f = tmp_path / "checkpoint.tar.gz"
    original = b"another payload"
    f.write_bytes(original)
    cid = client.upload_file(f)
    assert client.get_bytes(cid) == original


def test_upload_missing_file_raises(client, tmp_path):
    with pytest.raises(FileNotFoundError):
        client.upload_file(tmp_path / "does_not_exist.tar.gz")


def test_download_unknown_cid_raises_not_found(client):
    with pytest.raises(IPFSNotFoundError):
        client.get_bytes("Qmdoesnotexist")


def test_connection_error_raises_unavailable(client, fake_session, tmp_path):
    fake_session.raise_connection_error = True
    f = tmp_path / "x.tar.gz"
    f.write_bytes(b"data")
    with pytest.raises(IPFSUnavailableError):
        client.upload_file(f)


def test_timeout_raises_unavailable(client, fake_session, tmp_path):
    fake_session.raise_timeout = True
    f = tmp_path / "x.tar.gz"
    f.write_bytes(b"data")
    with pytest.raises(IPFSUnavailableError):
        client.upload_file(f)


# ---------------------------------------------------------------------- #
# FakeIPFS (used by the rest of the test suite) gets its own quick checks
# ---------------------------------------------------------------------- #
def test_fake_ipfs_round_trip(tmp_path):
    fake = FakeIPFS()
    f = tmp_path / "x.tar.gz"
    f.write_bytes(b"round trip me")
    cid = fake.upload_file(f)
    assert fake.get_bytes(cid) == b"round trip me"

    dest = tmp_path / "out.tar.gz"
    fake.download_file(cid, dest)
    assert dest.read_bytes() == b"round trip me"


def test_fake_ipfs_same_content_same_cid(tmp_path):
    fake = FakeIPFS()
    f1 = tmp_path / "a.bin"
    f2 = tmp_path / "b.bin"
    f1.write_bytes(b"identical content")
    f2.write_bytes(b"identical content")
    assert fake.upload_file(f1) == fake.upload_file(f2)


# ---------------------------------------------------------------------- #
# Optional: only runs if a real local Kubo daemon is reachable.
# ---------------------------------------------------------------------- #
def test_real_daemon_if_available(tmp_path):
    real_client = IPFSClient()
    if not real_client.is_available():
        pytest.skip("No local IPFS daemon reachable at http://127.0.0.1:5001")

    f = tmp_path / "real_checkpoint.tar.gz"
    f.write_bytes(b"real daemon integration check")
    cid = real_client.upload_file(f)
    assert real_client.get_bytes(cid) == b"real daemon integration check"
