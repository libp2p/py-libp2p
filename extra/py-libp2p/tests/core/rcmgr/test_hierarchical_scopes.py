from libp2p.rcmgr import Direction
from libp2p.rcmgr.manager import ResourceManager


class TestHierarchicalScopes:
    def test_service_limits_total_and_per_peer(self) -> None:
        rm = ResourceManager()
        rm.set_service_stream_limit("identify", 2)
        rm.set_service_peer_stream_limit("identify", 1)

        # Peer A can open 1
        assert rm.acquire_scoped_stream("peerA", Direction.OUTBOUND, service="identify")
        # Peer A cannot open another (per-peer)
        assert not rm.acquire_scoped_stream(
            "peerA", Direction.OUTBOUND, service="identify"
        )
        # Peer B can open 1 (total now 2)
        assert rm.acquire_scoped_stream("peerB", Direction.OUTBOUND, service="identify")
        # Any further opens should fail (total limit)
        assert not rm.acquire_scoped_stream(
            "peerC", Direction.OUTBOUND, service="identify"
        )

        # Cleanup and ensure counters decrement
        rm.release_scoped_stream("peerA", Direction.OUTBOUND, service="identify")
        rm.release_scoped_stream("peerB", Direction.OUTBOUND, service="identify")

    def test_protocol_limits_total_and_per_peer(self) -> None:
        rm = ResourceManager()
        rm.set_protocol_stream_limit("/yamux/1.0.0", 1)
        rm.set_protocol_peer_stream_limit("/yamux/1.0.0", 1)

        # First peer gets it
        assert rm.acquire_scoped_stream(
            "peerA", Direction.INBOUND, protocol="/yamux/1.0.0"
        )
        # Another peer cannot due to total=1
        assert not rm.acquire_scoped_stream(
            "peerB", Direction.INBOUND, protocol="/yamux/1.0.0"
        )

        rm.release_scoped_stream("peerA", Direction.INBOUND, protocol="/yamux/1.0.0")

        # Now peerB can obtain after release
        assert rm.acquire_scoped_stream(
            "peerB", Direction.INBOUND, protocol="/yamux/1.0.0"
        )
        rm.release_scoped_stream("peerB", Direction.INBOUND, protocol="/yamux/1.0.0")
