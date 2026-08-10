"""
Unit tests for mDNS listener component.
"""

import socket

from zeroconf import ServiceInfo, Zeroconf

from libp2p.abc import Multiaddr
from libp2p.discovery.mdns.listener import PeerListener
from libp2p.peer.id import ID
from libp2p.peer.peerstore import PeerStore


class TestPeerListener:
    """Unit tests for PeerListener."""

    def test_listener_initialization(self):
        """Test that listener initializes correctly."""
        peerstore = PeerStore()
        zeroconf = Zeroconf()
        service_type = "_p2p._udp.local."
        service_name = "local-peer._p2p._udp.local."

        listener = PeerListener(
            peerstore=peerstore,
            zeroconf=zeroconf,
            service_type=service_type,
            service_name=service_name,
        )

        assert listener.peerstore == peerstore
        assert listener.zeroconf == zeroconf
        assert listener.service_type == service_type
        assert listener.service_name == service_name
        assert listener.discovered_services == {}

        # Clean up
        listener.stop()
        zeroconf.close()

    def test_listener_extract_peer_info_from_dnsaddr(self):
        """Test PeerInfo extraction from spec-compliant dnsaddr TXT records."""
        peerstore = PeerStore()
        zeroconf = Zeroconf()

        listener = PeerListener(
            peerstore=peerstore,
            zeroconf=zeroconf,
            service_type="_p2p._udp.local.",
            service_name="local._p2p._udp.local.",
        )

        sample_peer_id = ID.from_base58(
            "QmNnooDu7bfjPFoTZYxMNLWUQJyrVwtbZg5gBMjTezGAJN"
        )
        hostname = socket.gethostname()
        local_ip = "192.168.1.100"

        # Spec-compliant: dnsaddr TXT record with full multiaddr
        sample_service_info = ServiceInfo(
            type_="_p2p._udp.local.",
            name="test-peer._p2p._udp.local.",
            port=8000,
            properties={
                b"dnsaddr": f"/ip4/{local_ip}/tcp/8000/p2p/{sample_peer_id}".encode(),
            },
            server=f"{hostname}.local.",
            addresses=[socket.inet_aton(local_ip)],
        )

        peer_info = listener._extract_peer_info(sample_service_info)

        assert peer_info is not None
        assert isinstance(peer_info.peer_id, ID)
        assert peer_info.peer_id == sample_peer_id
        assert len(peer_info.addrs) == 1
        assert all(isinstance(addr, Multiaddr) for addr in peer_info.addrs)
        assert f"/ip4/{local_ip}/tcp/8000" in str(peer_info.addrs[0])

        listener.stop()
        zeroconf.close()

    def test_listener_extract_peer_info_legacy_id(self):
        """Test PeerInfo extraction from legacy 'id' property with A/AAAA fallback."""
        peerstore = PeerStore()
        zeroconf = Zeroconf()

        listener = PeerListener(
            peerstore=peerstore,
            zeroconf=zeroconf,
            service_type="_p2p._udp.local.",
            service_name="local._p2p._udp.local.",
        )

        sample_peer_id = ID.from_base58(
            "QmNnooDu7bfjPFoTZYxMNLWUQJyrVwtbZg5gBMjTezGAJN"
        )
        hostname = socket.gethostname()
        local_ip = "192.168.1.100"

        # Legacy format: 'id' property, addresses from A/AAAA
        sample_service_info = ServiceInfo(
            type_="_p2p._udp.local.",
            name="test-peer._p2p._udp.local.",
            port=8000,
            properties={b"id": str(sample_peer_id).encode()},
            server=f"{hostname}.local.",
            addresses=[socket.inet_aton(local_ip)],
        )

        peer_info = listener._extract_peer_info(sample_service_info)

        assert peer_info is not None
        assert isinstance(peer_info.peer_id, ID)
        assert peer_info.peer_id == sample_peer_id
        assert len(peer_info.addrs) == 1
        assert "/tcp/8000" in str(peer_info.addrs[0])

        listener.stop()
        zeroconf.close()

    def test_listener_extract_peer_info_invalid_id(self):
        """Test PeerInfo extraction fails with invalid peer ID."""
        peerstore = PeerStore()
        zeroconf = Zeroconf()

        listener = PeerListener(
            peerstore=peerstore,
            zeroconf=zeroconf,
            service_type="_p2p._udp.local.",
            service_name="local._p2p._udp.local.",
        )

        hostname = socket.gethostname()
        local_ip = "192.168.1.100"

        service_info = ServiceInfo(
            type_="_p2p._udp.local.",
            name="invalid-peer._p2p._udp.local.",
            port=8000,
            properties={b"id": b"invalid_peer_id_format"},
            server=f"{hostname}.local.",
            addresses=[socket.inet_aton(local_ip)],
        )

        peer_info = listener._extract_peer_info(service_info)
        assert peer_info is None

        listener.stop()
        zeroconf.close()

    def test_listener_extract_peer_info_no_addrs(self):
        """Test PeerInfo extraction fails when no addresses available."""
        peerstore = PeerStore()
        zeroconf = Zeroconf()

        listener = PeerListener(
            peerstore=peerstore,
            zeroconf=zeroconf,
            service_type="_p2p._udp.local.",
            service_name="local._p2p._udp.local.",
        )

        sample_peer_id = ID.from_base58(
            "QmNnooDu7bfjPFoTZYxMNLWUQJyrVwtbZg5gBMjTezGAJN"
        )
        hostname = socket.gethostname()

        # Peer ID in TXT but no addresses in A/AAAA and no addr in dnsaddr
        sample_service_info = ServiceInfo(
            type_="_p2p._udp.local.",
            name="no-addrs._p2p._udp.local.",
            port=8000,
            properties={b"id": str(sample_peer_id).encode()},
            server=f"{hostname}.local.",
            addresses=[],
        )

        peer_info = listener._extract_peer_info(sample_service_info)
        assert peer_info is None

        listener.stop()
        zeroconf.close()
