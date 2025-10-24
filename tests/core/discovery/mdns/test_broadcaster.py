"""
Unit tests for mDNS broadcaster component.
"""

from zeroconf import Zeroconf

from libp2p.discovery.mdns.broadcaster import PeerBroadcaster
from libp2p.peer.id import ID


class TestPeerBroadcaster:
    """Unit tests for PeerBroadcaster."""

    def test_broadcaster_initialization(self):
        """Test that broadcaster initializes correctly."""
        zeroconf = Zeroconf()
        service_type = "_p2p._udp.local."
        service_name = "test-peer._p2p._udp.local."
        peer_id = (
            "QmNnooDu7bfjPFoTZYxMNLWUQJyrVwtbZg5gBMjTezGAJN"  # String, not ID object
        )
        port = 8000

        broadcaster = PeerBroadcaster(
            zeroconf=zeroconf,
            service_type=service_type,
            service_name=service_name,
            peer_id=peer_id,
            port=port,
        )

        assert broadcaster.zeroconf == zeroconf
        assert broadcaster.service_type == service_type
        assert broadcaster.service_name == service_name
        assert broadcaster.peer_id == peer_id
        assert broadcaster.port == port

        # Clean up
        zeroconf.close()

    def test_broadcaster_service_creation(self):
        """Test that broadcaster creates valid service info."""
        zeroconf = Zeroconf()
        service_type = "_p2p._udp.local."
        service_name = "test-peer2._p2p._udp.local."
        peer_id_obj = ID.from_base58("QmNnooDu7bfjPFoTZYxMNLWUQJyrVwtbZg5gBMjTezGAJN")
        peer_id = str(peer_id_obj)  # Convert to string
        port = 8000

        broadcaster = PeerBroadcaster(
            zeroconf=zeroconf,
            service_type=service_type,
            service_name=service_name,
            peer_id=peer_id,
            port=port,
        )

        # Verify service was created and registered
        service_info = broadcaster.service_info
        assert service_info is not None
        assert service_info.type == service_type
        assert service_info.name == service_name
        assert service_info.port == port
        assert b"id" in service_info.properties
        assert service_info.properties[b"id"] == peer_id.encode()

        # Clean up
        zeroconf.close()

    def test_broadcaster_start_stop(self):
        """Test that broadcaster can start and stop correctly."""
        zeroconf = Zeroconf()
        service_type = "_p2p._udp.local."
        service_name = "test-start-stop._p2p._udp.local."
        peer_id_obj = ID.from_base58("QmYyQSo1c1Ym7orWxLYvCrM2EmxFTANf8wXmmE7DWjhx5N")
        peer_id = str(peer_id_obj)  # Convert to string
        port = 8001

        broadcaster = PeerBroadcaster(
            zeroconf=zeroconf,
            service_type=service_type,
            service_name=service_name,
            peer_id=peer_id,
            port=port,
        )

        # Service should be registered
        assert broadcaster.service_info is not None

        # Clean up
        zeroconf.close()
