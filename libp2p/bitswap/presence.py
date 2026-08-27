import time

from libp2p.peer.id import ID as PeerID

from .cid import CIDObject


class BlockPresenceManager:
    """Manages tracking of which peers have or don't have specific blocks with TTL."""

    def __init__(self, ttl_seconds: float = 60.0):
        self.ttl = ttl_seconds
        # peer_id -> cid -> timestamp
        self._have: dict[PeerID, dict[CIDObject, float]] = {}
        # cid -> peer_id -> timestamp
        self._dont_have: dict[CIDObject, dict[PeerID, float]] = {}

    def add_have(self, peer_id: PeerID, cid: CIDObject) -> None:
        if peer_id not in self._have:
            self._have[peer_id] = {}
        self._have[peer_id][cid] = time.time()

    def add_dont_have(self, peer_id: PeerID, cid: CIDObject) -> None:
        if cid not in self._dont_have:
            self._dont_have[cid] = {}
        self._dont_have[cid][peer_id] = time.time()

    def remove_have(self, peer_id: PeerID, cid: CIDObject) -> None:
        if peer_id in self._have and cid in self._have[peer_id]:
            del self._have[peer_id][cid]
            if not self._have[peer_id]:
                del self._have[peer_id]

    def remove_dont_have(self, cid: CIDObject) -> None:
        if cid in self._dont_have:
            del self._dont_have[cid]

    def remove_peer(self, peer_id: PeerID) -> None:
        """Drop all presence state recorded for a peer (e.g. on disconnect)."""
        self._have.pop(peer_id, None)
        for cid in list(self._dont_have.keys()):
            self._dont_have[cid].pop(peer_id, None)
            if not self._dont_have[cid]:
                del self._dont_have[cid]

    def get_expected_peers(self, cid: CIDObject) -> set[PeerID]:
        """Get peers that are expected to have the block."""
        return {p for p in self._have if cid in self._have[p]}

    def get_dont_have_peers(self, cid: CIDObject) -> set[PeerID]:
        """Get peers that explicitly responded with DONT_HAVE."""
        return set(self._dont_have.get(cid, {}).keys())

    def get_expected_cids_for_peer(self, peer_id: PeerID) -> set[CIDObject]:
        """Get all CIDs expected from a specific peer."""
        return set(self._have.get(peer_id, {}).keys())

    def get_expected_for_peer(self, peer_id: PeerID) -> set[CIDObject]:
        """Alias for get_expected_cids_for_peer."""
        return self.get_expected_cids_for_peer(peer_id)

    def remove_have_from_all(self, cid: CIDObject) -> None:
        """Remove a CID from all peers' expected blocks."""
        for peer_id in list(self._have.keys()):
            if cid in self._have[peer_id]:
                del self._have[peer_id][cid]
                if not self._have[peer_id]:
                    del self._have[peer_id]

    def cleanup_expired(self) -> None:
        now = time.time()
        # Clean up _have
        for peer_id in list(self._have.keys()):
            for cid in list(self._have[peer_id].keys()):
                if now - self._have[peer_id][cid] > self.ttl:
                    del self._have[peer_id][cid]
            if not self._have[peer_id]:
                del self._have[peer_id]

        # Clean up _dont_have
        for cid in list(self._dont_have.keys()):
            for peer_id in list(self._dont_have[cid].keys()):
                if now - self._dont_have[cid][peer_id] > self.ttl:
                    del self._dont_have[cid][peer_id]
            if not self._dont_have[cid]:
                del self._dont_have[cid]
