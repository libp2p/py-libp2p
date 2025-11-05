from libp2p.crypto.rsa import create_new_key_pair
from libp2p.peer.id import ID
from libp2p.rcmgr.manager import ResourceManager


def _valid_peer_id_base58() -> str:
    key_pair = create_new_key_pair()
    pid = ID.from_pubkey(key_pair.public_key)
    return pid.to_base58()


class TestRateLimiting:
    def test_burst_limit_enforced_per_peer(self) -> None:
        # Configure a very small burst so we can test quickly
        rm = ResourceManager(
            enable_rate_limiting=True,
            # Use a tiny, positive refill rate to satisfy config validation
            connections_per_peer_per_sec=1e-9,
            burst_connections_per_peer=3.0,
        )

        peer = _valid_peer_id_base58()

        # First 3 should pass
        assert rm.acquire_connection(peer) is True
        assert rm.acquire_connection(peer) is True
        assert rm.acquire_connection(peer) is True

        # 4th should be rate limited
        assert rm.acquire_connection(peer) is False

    def test_rate_limit_independent_across_peers(self) -> None:
        rm = ResourceManager(
            enable_rate_limiting=True,
            connections_per_peer_per_sec=1e-9,
            burst_connections_per_peer=1.0,
        )
        p1 = _valid_peer_id_base58()
        p2 = _valid_peer_id_base58()

        assert rm.acquire_connection(p1) is True
        # p1 blocked now
        assert rm.acquire_connection(p1) is False

        # p2 should be allowed (separate bucket)
        assert rm.acquire_connection(p2) is True
