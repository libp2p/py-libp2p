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

        # Verify peer_name is derived from service_name (spec compliance)
        assert broadcaster.peer_name == "test-peer"

        # Verify server field uses peer_name, not system hostname
        # Note: zeroconf strips trailing dot from FQDN
        assert broadcaster.service_info is not None
        server = broadcaster.service_info.server
        assert server is not None and server.startswith("test-peer.local")

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
        assert b"dnsaddr" in service_info.properties
        dnsaddr_val = service_info.properties[b"dnsaddr"]
        assert dnsaddr_val is not None
        dnsaddr = dnsaddr_val.decode()
        assert f"/p2p/{peer_id}" in dnsaddr

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

    def test_is_suitable_for_mdns(self):
        """Test address filtering for mDNS suitability."""
        # Suitable: direct IP addresses
        assert PeerBroadcaster.is_suitable_for_mdns("/ip4/192.168.1.1/tcp/4001")
        assert PeerBroadcaster.is_suitable_for_mdns("/ip6/fe80::1/tcp/4001")
        assert PeerBroadcaster.is_suitable_for_mdns("/ip4/192.168.1.1/udp/4001/quic-v1")

        # Suitable: .local DNS names
        assert PeerBroadcaster.is_suitable_for_mdns("/dns/myhost.local/tcp/4001")
        assert PeerBroadcaster.is_suitable_for_mdns("/dns4/MyHost.LOCAL/tcp/4001")

        # Not suitable: circuit relay
        assert not PeerBroadcaster.is_suitable_for_mdns(
            "/ip4/198.51.100.1/tcp/4001/p2p/12D3KooWDpJ7As7BWAwRMfu1VU2WCqNjvq387JEYKDBj4kx6nXTN/p2p-circuit/p2p/12D3KooWGzBXWNvHpLALvz3jhwdCF6kfv9MfhMn9CuS2MBD2GpSy"
        )

        # Not suitable: browser transports
        assert not PeerBroadcaster.is_suitable_for_mdns(
            "/ip4/192.168.1.1/udp/4001/quic-v1/webtransport"
        )
        assert not PeerBroadcaster.is_suitable_for_mdns(
            "/ip4/192.168.1.1/udp/4001/webrtc"
        )
        assert not PeerBroadcaster.is_suitable_for_mdns("/ip4/192.168.1.1/tcp/4001/ws")
        assert not PeerBroadcaster.is_suitable_for_mdns("/ip4/192.168.1.1/tcp/443/wss")

        # Not suitable: non-.local DNS
        assert not PeerBroadcaster.is_suitable_for_mdns("/dns4/example.com/tcp/4001")
        assert not PeerBroadcaster.is_suitable_for_mdns("/dns6/example.com/tcp/4001")

    def test_broadcaster_filters_unsuitable_addrs(self):
        """Test that broadcaster filters out unsuitable listen addresses."""
        zeroconf = Zeroconf()
        peer_id_obj = ID.from_base58("QmNnooDu7bfjPFoTZYxMNLWUQJyrVwtbZg5gBMjTezGAJN")
        peer_id = str(peer_id_obj)

        # Include a mix of suitable and unsuitable addresses
        listen_addrs = [
            "/ip4/192.168.1.1/tcp/4001",
            "/ip4/192.168.1.1/udp/4001/quic-v1/webtransport",  # unsuitable
            "/ip4/192.168.1.1/tcp/4001/ws",  # unsuitable
        ]

        broadcaster = PeerBroadcaster(
            zeroconf=zeroconf,
            service_type="_p2p._udp.local.",
            service_name="test-peer._p2p._udp.local.",
            peer_id=peer_id,
            port=4001,
            listen_addrs=listen_addrs,
        )

        # Only the suitable address should be in the TXT record
        assert broadcaster.service_info is not None
        assert b"dnsaddr" in broadcaster.service_info.properties
        dnsaddr_val = broadcaster.service_info.properties[b"dnsaddr"]
        assert dnsaddr_val is not None
        dnsaddr = dnsaddr_val.decode()
        assert "/ip4/192.168.1.1/tcp/4001" in dnsaddr
        assert "/ws" not in dnsaddr
        assert "/webtransport" not in dnsaddr

        zeroconf.close()
