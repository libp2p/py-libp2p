"""
Test to confirm bug: find_peer doesn't re-check peerstore after network lookup.

During a network lookup (find_closest_peers_network), the target peer's
signed record may be discovered and added to the peerstore. But find_peer
only checks closest_peers list after the lookup, not the peerstore.

In go-libp2p, FindPeer checks the peerstore after the lookup completes.
"""

import logging

from multiaddr import Multiaddr
import trio

from libp2p.kad_dht.peer_routing import PeerRouting
from libp2p.peer.id import ID

logger = logging.getLogger(__name__)


async def test_find_peer_rechecks_peerstore_after_lookup():
    """
    Verify that find_peer re-checks the peerstore after network lookup.

    The peerstore should be checked again after the network lookup because
    during the iterative lookup, the target peer's signed record may have
    been discovered and added to the peerstore (via maybe_consume_signed_record)
    even if it wasn't in the top 20 closest peers.
    """
    from unittest.mock import MagicMock

    local_id = ID(b"\x00" * 32)
    target_id = ID(b"\xff" + b"\x00" * 31)

    host = MagicMock()
    host.get_id = MagicMock(return_value=local_id)

    # Mutable state to simulate peerstore updates during lookup
    peerstore_has_target = False

    def mock_addrs(peer_id):
        if peer_id == target_id and peerstore_has_target:
            return [Multiaddr("/ip4/127.0.0.1/tcp/9090")]
        return []

    peerstore = MagicMock()
    peerstore.addrs = MagicMock(side_effect=mock_addrs)
    peerstore.peer_ids = MagicMock(return_value=[])
    host.get_peerstore = MagicMock(return_value=peerstore)
    host.get_connected_peers = MagicMock(return_value=[])

    routing_table = MagicMock()
    routing_table.find_local_closest_peers = MagicMock(return_value=[])
    routing_table.get_peer_info = MagicMock(return_value=None)

    peer_routing = PeerRouting(host, routing_table)

    # Mock find_closest_peers_network to simulate:
    # 1. Target peer discovered during lookup (added to peerstore)
    # 2. But NOT in the top 20 closest_peers result
    async def mock_find_closest(target_key: bytes, count: int = 20) -> list[ID]:
        nonlocal peerstore_has_target
        # Simulate the target peer being discovered during the lookup
        peerstore_has_target = True
        # Return a different peer, NOT the target
        return [ID(b"\xee" + b"\x00" * 31)]

    peer_routing.find_closest_peers_network = mock_find_closest  # type: ignore[assignment]

    result = await peer_routing.find_peer(target_id)

    if result is None:
        raise AssertionError(
            "BUG: find_peer returned None even though target peer's "
            "addresses were added to peerstore during network lookup. "
            "Should re-check peerstore after lookup."
        )
    else:
        assert result.peer_id == target_id
        print(f"PASS: find_peer found peer {target_id} via peerstore re-check")


async def main():
    try:
        await test_find_peer_rechecks_peerstore_after_lookup()
    except AssertionError as e:
        logger.error(f"BUG CONFIRMED: {e}")
        raise
    except Exception as e:
        logger.error(f"Test error (may indicate bug): {e}")
        raise


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    trio.run(main)
