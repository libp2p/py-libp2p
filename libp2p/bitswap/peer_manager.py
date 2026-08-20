import time

from libp2p.bitswap.cid import CIDObject
from libp2p.peer.id import ID as PeerID


class PeerStats:
    def __init__(self) -> None:
        self.requests_sent = 0
        self.blocks_delivered = 0
        self.bytes_delivered = 0
        self.timeouts = 0
        # Default latency of 1 second for untried peers
        self.ema_latency = 1.0
        self._pending_requests: dict[CIDObject, float] = {}


class BitswapPeerManager:
    """
    Tracks performance of Bitswap peers to optimize routing.
    """

    def __init__(self) -> None:
        self.peers: dict[PeerID, PeerStats] = {}

    def _get_stats(self, peer_id: PeerID) -> PeerStats:
        if peer_id not in self.peers:
            self.peers[peer_id] = PeerStats()
        return self.peers[peer_id]

    def record_request(self, peer_id: PeerID, cid: CIDObject) -> None:
        stats = self._get_stats(peer_id)
        stats.requests_sent += 1
        stats._pending_requests[cid] = time.time()

    def record_delivery(self, peer_id: PeerID, cid: CIDObject, data_size: int) -> None:
        stats = self._get_stats(peer_id)
        stats.blocks_delivered += 1
        stats.bytes_delivered += data_size

        if cid in stats._pending_requests:
            latency = time.time() - stats._pending_requests.pop(cid)
            # Update EMA latency (alpha = 0.125)
            stats.ema_latency = (0.125 * latency) + (0.875 * stats.ema_latency)

    def record_timeout(self, peer_id: PeerID, cid: CIDObject) -> None:
        stats = self._get_stats(peer_id)
        stats.timeouts += 1
        if cid in stats._pending_requests:
            del stats._pending_requests[cid]

    def remove_peer(self, peer_id: PeerID) -> None:
        """Drop all stats recorded for a peer (e.g. on disconnect)."""
        self.peers.pop(peer_id, None)

    def get_best_peers(self, candidates: set[PeerID], count: int) -> list[PeerID]:
        """Rank peers based on latency and success rate."""

        def score(peer_id: PeerID) -> float:
            stats = self._get_stats(peer_id)
            success_rate = (
                (stats.blocks_delivered / stats.requests_sent)
                if stats.requests_sent > 0
                else 0.5
            )
            # Higher score is better: high success rate, low latency
            return success_rate / max(stats.ema_latency, 0.001)

        sorted_peers = sorted(candidates, key=score, reverse=True)
        return sorted_peers[:count]
