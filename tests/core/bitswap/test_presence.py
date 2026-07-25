import time

from libp2p.bitswap.cid import compute_cid_v1
from libp2p.bitswap.presence import BlockPresenceManager
from libp2p.peer.id import ID as PeerID


class TestBlockPresenceManager:
    def test_add_and_remove(self):
        manager = BlockPresenceManager(ttl_seconds=60.0)
        peer1 = PeerID(b"peer1")
        cid1 = compute_cid_v1(b"data1")

        manager.add_have(peer1, cid1)
        assert cid1 in manager.get_expected_cids_for_peer(peer1)
        assert peer1 in manager.get_expected_peers(cid1)

        manager.add_dont_have(peer1, cid1)
        assert peer1 in manager.get_dont_have_peers(cid1)

        manager.remove_have(peer1, cid1)
        assert cid1 not in manager.get_expected_cids_for_peer(peer1)

        manager.remove_dont_have(cid1)
        assert peer1 not in manager.get_dont_have_peers(cid1)

    def test_cleanup_expired(self, monkeypatch):
        manager = BlockPresenceManager(ttl_seconds=1.0)
        peer1 = PeerID(b"peer1")
        cid1 = compute_cid_v1(b"data1")
        cid2 = compute_cid_v1(b"data2")

        # Mock time to T=0
        monkeypatch.setattr(time, "time", lambda: 0.0)
        manager.add_have(peer1, cid1)
        manager.add_dont_have(peer1, cid1)

        # Mock time to T=0.5 (Not expired)
        monkeypatch.setattr(time, "time", lambda: 0.5)
        manager.add_have(peer1, cid2)
        manager.cleanup_expired()

        assert cid1 in manager.get_expected_cids_for_peer(peer1)
        assert cid2 in manager.get_expected_cids_for_peer(peer1)
        assert peer1 in manager.get_dont_have_peers(cid1)

        # Mock time to T=1.1 (cid1 expired, cid2 not expired)
        monkeypatch.setattr(time, "time", lambda: 1.1)
        manager.cleanup_expired()

        assert cid1 not in manager.get_expected_cids_for_peer(peer1)
        assert cid2 in manager.get_expected_cids_for_peer(peer1)
        assert peer1 not in manager.get_dont_have_peers(cid1)
