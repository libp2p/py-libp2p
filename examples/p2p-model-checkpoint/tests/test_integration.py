"""
End-to-end integration test covering the full MVP flow described in the
README:

    Peer A trains -> checkpoints -> uploads to IPFS -> gets a CID
    -> announces the CID over libp2p -> Peer B receives it
    -> Peer B downloads from IPFS -> loads -> continues training

Uses :class:`tests.fake_ipfs.FakeIPFS` as a shared in-memory "IPFS network"
between the two peers (a real Kubo daemon works identically -- see
``test_ipfs.py::test_real_daemon_if_available`` for that path) and two real,
in-process libp2p hosts talking over loopback TCP.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from libp2p.peer.peerinfo import PeerInfo
from libp2p.utils.address_validation import get_available_interfaces

from examples.iris_data import load_partition
from p2p_checkpoint.peer import Peer
from p2p_checkpoint.sync import sync_with_peer
from tests.fake_ipfs import FakeIPFS


@pytest.fixture()
def shared_ipfs():
    return FakeIPFS()


def _make_peer(name: str, tmp_path: Path, ipfs: FakeIPFS, seed_byte: bytes) -> Peer:
    return Peer(name, tmp_path / name, ipfs=ipfs, seed=seed_byte * 32)


async def test_full_flow_train_checkpoint_ipfs_libp2p_sync(tmp_path, shared_ipfs):
    peer_a = _make_peer("peer-a", tmp_path, shared_ipfs, b"\x01")
    peer_b = _make_peer("peer-b", tmp_path, shared_ipfs, b"\x02")

    async with (
        peer_a.host.run(listen_addrs=get_available_interfaces(0)),
        peer_b.host.run(listen_addrs=get_available_interfaces(0)),
    ):
        info_a = PeerInfo(peer_a.host.get_id(), peer_a.host.get_addrs())
        await peer_b.host.connect(info_a)

        # 1-5: Peer A trains, checkpoints, uploads to IPFS, gets a CID.
        X_train, y_train, X_test, y_test, feature_names, class_names = load_partition(
            "peer-a"
        )
        cid, round_ = peer_a.train_and_publish(
            X_train,
            y_train,
            feature_names=feature_names,
            class_names=class_names,
            eval_data=(X_test, y_test),
        )
        assert round_ == 1
        assert cid in shared_ipfs.store
        assert peer_a.db.latest_round() == 1

        # 6-7: announce the CID to Peer B over libp2p.
        ack = await peer_a.announce_latest(peer_b.host.get_id())
        assert ack is not None
        assert ack.found is False  # B doesn't have it *yet* -- it hasn't fetched.

        # 8-10: Peer B fetches from IPFS via a sync pull, loads, and verifies.
        outcome = await sync_with_peer(peer_b, peer_a.host.get_id())
        assert outcome.action == "updated"
        assert outcome.local_round_after == 1
        assert peer_b.db.latest_round() == 1
        assert peer_b.model is not None
        assert peer_b.model.is_fitted

        # The two models should agree closely on the held-out test set --
        # they're the literal same fitted estimator, just round-tripped
        # through disk + IPFS + libp2p.
        np.testing.assert_array_equal(
            peer_a.model.predict(X_test), peer_b.model.predict(X_test)
        )

        # 11: Peer B continues training on its own shard, producing round 2.
        Xb_train, yb_train, *_ = load_partition("peer-b")
        cid2, round2 = peer_b.train_and_publish(Xb_train, yb_train)
        assert round2 == 2
        assert cid2 in shared_ipfs.store
        assert peer_b.db.latest_round() == 2

    peer_a.close()
    peer_b.close()


async def test_never_downgrades_on_sync(tmp_path, shared_ipfs):
    """A peer that is *ahead* of the peer it syncs against must not be
    dragged backwards (README > Never Automatically Downgrade)."""
    peer_a = _make_peer("peer-a", tmp_path, shared_ipfs, b"\x03")
    peer_b = _make_peer("peer-b", tmp_path, shared_ipfs, b"\x04")

    async with (
        peer_a.host.run(listen_addrs=get_available_interfaces(0)),
        peer_b.host.run(listen_addrs=get_available_interfaces(0)),
    ):
        info_a = PeerInfo(peer_a.host.get_id(), peer_a.host.get_addrs())
        await peer_b.host.connect(info_a)

        X_train, y_train, *_ = load_partition("peer-a")

        # A trains 3 rounds; B (independently, not via sync) trains 5.
        for _ in range(3):
            peer_a.train_and_publish(X_train, y_train)
        for _ in range(5):
            peer_b.train_and_publish(X_train, y_train)

        assert peer_a.db.latest_round() == 3
        assert peer_b.db.latest_round() == 5

        outcome = await sync_with_peer(peer_b, peer_a.host.get_id())
        assert outcome.action == "remote_behind"
        assert peer_b.db.latest_round() == 5  # unchanged

    peer_a.close()
    peer_b.close()


async def test_sync_against_peer_with_no_checkpoints(tmp_path, shared_ipfs):
    peer_a = _make_peer("peer-a", tmp_path, shared_ipfs, b"\x05")
    peer_b = _make_peer("peer-b", tmp_path, shared_ipfs, b"\x06")

    async with (
        peer_a.host.run(listen_addrs=get_available_interfaces(0)),
        peer_b.host.run(listen_addrs=get_available_interfaces(0)),
    ):
        info_a = PeerInfo(peer_a.host.get_id(), peer_a.host.get_addrs())
        await peer_b.host.connect(info_a)

        outcome = await sync_with_peer(peer_b, peer_a.host.get_id())
        assert outcome.action == "remote_empty"
        assert peer_b.db.latest_round() == 0

    peer_a.close()
    peer_b.close()
