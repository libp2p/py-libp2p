"""Tests for FileSystemKeyStore and new_host identity provider / keystore wiring."""

from __future__ import annotations

import os
from pathlib import Path
import stat
import tempfile

import pytest

from libp2p import new_host
from libp2p.crypto.ed25519 import create_new_key_pair
from libp2p.crypto.keystore import (
    FileSystemKeyStore,
    provider_from_keystore,
    provider_from_path,
    provider_new_ed25519,
)
from libp2p.identity_utils import save_identity
from libp2p.peer.id import ID


def test_keystore_put_get_list_delete_has() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        store = FileSystemKeyStore(tmpdir)
        kp_a = create_new_key_pair()
        kp_b = create_new_key_pair()

        assert store.list() == []
        assert not store.has("alpha")

        store.put("alpha", kp_a)
        store.put("beta", kp_b)

        assert store.has("alpha")
        assert set(store.list()) == {"alpha", "beta"}
        assert store.get("alpha").private_key.to_bytes() == kp_a.private_key.to_bytes()
        assert store.get("beta").private_key.to_bytes() == kp_b.private_key.to_bytes()

        if os.name != "nt":
            mode = stat.S_IMODE((Path(tmpdir) / "alpha.key").stat().st_mode)
            assert mode == 0o600

        store.delete("alpha")
        assert not store.has("alpha")
        assert store.list() == ["beta"]

        with pytest.raises(FileNotFoundError):
            store.get("alpha")
        with pytest.raises(FileNotFoundError):
            store.delete("alpha")


def test_keystore_rejects_unsafe_names() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        store = FileSystemKeyStore(tmpdir)
        kp = create_new_key_pair()
        for bad in ("../escape", "a/b", "a\\b", "", "..", "."):
            with pytest.raises(ValueError):
                store.put(bad, kp)


def test_provider_helpers() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "id.key"
        original = create_new_key_pair()
        save_identity(original, path)

        loaded = provider_from_path(path)()
        assert loaded.private_key.to_bytes() == original.private_key.to_bytes()

        store = FileSystemKeyStore(tmpdir)
        store.put("default", original)
        assert (
            provider_from_keystore(store, "default")().private_key.to_bytes()
            == original.private_key.to_bytes()
        )

        fresh = provider_new_ed25519()()
        assert fresh.private_key.to_bytes() != original.private_key.to_bytes()


@pytest.mark.trio
async def test_new_host_key_pair_provider_stable_peer_id() -> None:
    key_pair = create_new_key_pair()
    host_1 = new_host(key_pair_provider=lambda: key_pair)
    host_2 = new_host(key_pair_provider=lambda: key_pair)
    assert host_1.get_id() == host_2.get_id() == ID.from_pubkey(key_pair.public_key)


@pytest.mark.trio
async def test_new_host_keystore_create_then_reload_same_peer_id() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        store = FileSystemKeyStore(tmpdir)
        host_1 = new_host(keystore=store, identity_name="node")
        peer_id = host_1.get_id()
        assert store.has("node")

        host_2 = new_host(keystore=FileSystemKeyStore(tmpdir), identity_name="node")
        assert host_2.get_id() == peer_id


@pytest.mark.trio
async def test_new_host_mutual_exclusion_raises() -> None:
    key_pair = create_new_key_pair()
    with tempfile.TemporaryDirectory() as tmpdir:
        store = FileSystemKeyStore(tmpdir)
        with pytest.raises(ValueError, match="at most one"):
            new_host(key_pair=key_pair, key_pair_provider=lambda: key_pair)
        with pytest.raises(ValueError, match="at most one"):
            new_host(key_pair=key_pair, keystore=store)
        with pytest.raises(ValueError, match="at most one"):
            new_host(key_pair_provider=lambda: key_pair, keystore=store)


@pytest.mark.trio
async def test_default_new_host_writes_nothing_without_keystore() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        cwd = Path.cwd()
        try:
            os.chdir(tmpdir)
            host_a = new_host()
            host_b = new_host()
            assert host_a.get_id() != host_b.get_id()
            assert list(Path(tmpdir).iterdir()) == []
        finally:
            os.chdir(cwd)
