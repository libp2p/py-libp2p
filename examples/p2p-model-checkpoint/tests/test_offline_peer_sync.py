"""
test_offline_peer_sync.py
--------------------------

The central scenario the whole project exists to demonstrate
(README > The Most Important Feature: Offline Peer, > Most Important
Integration Test):

    1. Start Peer A
    2. Start Peer B
    3. B syncs and receives checkpoint round 1
    4. Stop B
    5. A keeps training, producing checkpoints round 2, 3, 4 -- all
       uploaded to IPFS while B is offline and can't be reached
    6. B starts again (same identity, same on-disk state -- i.e. a real
       process restart, not just "still running")
    7. B asks A (now connected again) for the latest checkpoint
    8. B receives CID for round 4
    9. B downloads it from IPFS
    10. B loads checkpoint round 4

If this test passes, the "peer offline, misses updates, catches up later
via IPFS" behavior that differentiates this project from a plain
upload-and-forget model share is proven end to end.
"""

from __future__ import annotations

from pathlib import Path

from libp2p.peer.peerinfo import PeerInfo
from libp2p.utils.address_validation import get_available_interfaces

from examples.iris_data import load_partition
from p2p_checkpoint.peer import Peer
from p2p_checkpoint.sync import sync_with_peer
from tests.fake_ipfs import FakeIPFS

PEER_A_SEED = b"\xAA" * 32
PEER_B_SEED = b"\xBB" * 32


async def test_offline_peer_catches_up_after_reconnecting(tmp_path: Path):
    shared_ipfs = FakeIPFS()
    a_dir = tmp_path / "peer-a"
    b_dir = tmp_path / "peer-b"

    X_train, y_train, *_ = load_partition("peer-a")

    # --- Step 1 & 2: start Peer A and Peer B, B syncs to round 1 -------- #
    peer_a = Peer("peer-a", a_dir, ipfs=shared_ipfs, seed=PEER_A_SEED)
    peer_b = Peer("peer-b", b_dir, ipfs=shared_ipfs, seed=PEER_B_SEED)

    async with (
        peer_a.host.run(listen_addrs=get_available_interfaces(0)),
        peer_b.host.run(listen_addrs=get_available_interfaces(0)),
    ):
        info_a = PeerInfo(peer_a.host.get_id(), peer_a.host.get_addrs())
        await peer_b.host.connect(info_a)

        peer_a.train_and_publish(X_train, y_train)  # round 1
        assert peer_a.db.latest_round() == 1

        outcome = await sync_with_peer(peer_b, peer_a.host.get_id())
        assert outcome.action == "updated"
        assert peer_b.db.latest_round() == 1

    # --- Step 4: "stop" Peer B -- the host context above has exited, so B
    # is no longer listening or reachable. We also drop the Python object
    # (and close its DB handle) to make sure nothing keeps it alive.
    b_round_when_stopped = peer_b.db.latest_round()
    peer_b_original_id = peer_b.peer_id
    peer_b.close()
    del peer_b

    # --- Step 5: Peer A keeps training while B is offline, unreachable -- #
    async with peer_a.host.run(listen_addrs=get_available_interfaces(0)):
        peer_a.train_and_publish(X_train, y_train)  # round 2
        peer_a.train_and_publish(X_train, y_train)  # round 3
        peer_a.train_and_publish(X_train, y_train)  # round 4
    assert peer_a.db.latest_round() == 4
    # All four rounds are sitting in "IPFS" right now, independent of
    # whether any peer is currently listening for them.
    assert len(shared_ipfs.store) == 4

    # --- Step 6: Peer B "starts again" -- same identity (same seed) and
    # same on-disk data directory, i.e. this models a real process restart,
    # not merely "the object is still around".
    peer_b_restarted = Peer("peer-b", b_dir, ipfs=shared_ipfs, seed=PEER_B_SEED)
    # Same seed => same libp2p identity as before the "restart".
    assert peer_b_restarted.peer_id == peer_b_original_id
    assert peer_b_restarted.db.latest_round() == b_round_when_stopped == 1

    async with (
        peer_a.host.run(listen_addrs=get_available_interfaces(0)),
        peer_b_restarted.host.run(listen_addrs=get_available_interfaces(0)),
    ):
        info_a = PeerInfo(peer_a.host.get_id(), peer_a.host.get_addrs())

        # --- Step 7: B reconnects to A and asks for the latest --------- #
        await peer_b_restarted.host.connect(info_a)
        outcome = await sync_with_peer(peer_b_restarted, peer_a.host.get_id())

        # --- Step 8 & 9: B received CID for round 4 and fetched it from IPFS
        assert outcome.action == "updated"
        assert outcome.local_round_before == 1
        assert outcome.remote_round == 4
        assert outcome.cid is not None

        # --- Step 10: B loaded checkpoint round 4 ----------------------- #
        assert peer_b_restarted.db.latest_round() == 4
        assert peer_b_restarted.model is not None
        assert peer_b_restarted.model.is_fitted

        latest_record = peer_b_restarted.db.latest()
        assert latest_record.round == 4
        assert latest_record.origin == "remote"
        assert latest_record.cid == outcome.cid

    peer_a.close()
    peer_b_restarted.close()


async def test_offline_peer_is_ahead_and_does_not_downgrade_after_reconnect(
    tmp_path: Path,
):
    """A variant of the offline scenario where the *offline* peer kept
    training locally while disconnected (e.g. on cached/local data) and
    comes back ahead of the peer it reconnects to. It must keep its own,
    newer state -- see README > Never Automatically Downgrade."""
    shared_ipfs = FakeIPFS()
    a_dir = tmp_path / "peer-a"
    b_dir = tmp_path / "peer-b"

    X_train, y_train, *_ = load_partition("peer-a")

    peer_a = Peer("peer-a", a_dir, ipfs=shared_ipfs, seed=PEER_A_SEED)
    peer_b = Peer("peer-b", b_dir, ipfs=shared_ipfs, seed=PEER_B_SEED)

    peer_a.train_and_publish(X_train, y_train)  # A: round 1

    # B was never connected to A at all; it just trains locally, offline,
    # racing ahead on its own.
    for _ in range(3):
        peer_b.train_and_publish(X_train, y_train)  # B: rounds 1, 2, 3
    assert peer_b.db.latest_round() == 3

    async with (
        peer_a.host.run(listen_addrs=get_available_interfaces(0)),
        peer_b.host.run(listen_addrs=get_available_interfaces(0)),
    ):
        info_a = PeerInfo(peer_a.host.get_id(), peer_a.host.get_addrs())
        await peer_b.host.connect(info_a)

        outcome = await sync_with_peer(peer_b, peer_a.host.get_id())
        assert outcome.action == "remote_behind"
        assert peer_b.db.latest_round() == 3  # unchanged, no downgrade

    peer_a.close()
    peer_b.close()
