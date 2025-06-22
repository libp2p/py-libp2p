"""
Comprehensive integration tests for mDNS discovery functionality.
"""

import socket

from zeroconf import Zeroconf

from libp2p.discovery.mdns.broadcaster import PeerBroadcaster
from libp2p.discovery.mdns.listener import PeerListener
from libp2p.peer.id import ID
from libp2p.peer.peerstore import PeerStore


class TestMDNSDiscovery:
    """Comprehensive integration tests for mDNS peer discovery."""

    def test_one_host_finds_another(self):
        """Test that one host can find another host using mDNS."""
        # Create two separate Zeroconf instances to simulate different hosts
        host1_zeroconf = Zeroconf()
        host2_zeroconf = Zeroconf()

        try:
            # Host 1: Set up as broadcaster (the host to be discovered)
            host1_peer_id_obj = ID.from_base58(
                "QmNnooDu7bfjPFoTZYxMNLWUQJyrVwtbZg5gBMjTezGAJN"
            )
            host1_peer_id = str(host1_peer_id_obj)  # Convert to string
            host1_broadcaster = PeerBroadcaster(
                zeroconf=host1_zeroconf,
                service_type="_p2p._udp.local.",
                service_name="host1._p2p._udp.local.",
                peer_id=host1_peer_id,
                port=8000,
            )

            # Host 2: Set up as listener (the host that discovers others)
            host2_peerstore = PeerStore()
            host2_listener = PeerListener(
                peerstore=host2_peerstore,
                zeroconf=host2_zeroconf,
                service_type="_p2p._udp.local.",
                service_name="host2._p2p._udp.local.",
            )

            # Host 1 registers its service for discovery
            host1_broadcaster.register()

            # Verify that host2 discovered host1
            assert len(host2_listener.discovered_services) > 0
            assert "host1._p2p._udp.local." in host2_listener.discovered_services

            # Verify that host1's peer info was added to host2's peerstore
            discovered_peer_id = host2_listener.discovered_services[
                "host1._p2p._udp.local."
            ]
            assert str(discovered_peer_id) == host1_peer_id

            # Verify addresses were added to peerstore
            try:
                addrs = host2_peerstore.addrs(discovered_peer_id)
                assert len(addrs) > 0
                # Should be TCP since we always use TCP protocol
                assert "/tcp/8000" in str(addrs[0])
            except Exception:
                # If no addresses found, the discovery didn't work properly
                assert False, "Host1 addresses should be in Host2's peerstore"

            # Clean up
            host1_broadcaster.unregister()
            host2_listener.stop()

        finally:
            host1_zeroconf.close()
            host2_zeroconf.close()

    def test_service_info_extraction(self):
        """Test service info extraction functionality."""
        peerstore = PeerStore()
        zeroconf = Zeroconf()

        try:
            listener = PeerListener(
                peerstore=peerstore,
                zeroconf=zeroconf,
                service_type="_p2p._udp.local.",
                service_name="test-listener._p2p._udp.local.",
            )

            # Create a test service info
            test_peer_id = ID.from_base58(
                "QmYyQSo1c1Ym7orWxLYvCrM2EmxFTANf8wXmmE7DWjhx5N"
            )
            hostname = socket.gethostname()

            from zeroconf import ServiceInfo

            service_info = ServiceInfo(
                type_="_p2p._udp.local.",
                name="test-service._p2p._udp.local.",
                port=8001,
                properties={b"id": str(test_peer_id).encode()},
                server=f"{hostname}.local.",
                addresses=[socket.inet_aton("192.168.1.100")],
            )

            # Test extraction
            peer_info = listener._extract_peer_info(service_info)

            assert peer_info is not None
            assert peer_info.peer_id == test_peer_id
            assert len(peer_info.addrs) == 1
            assert "/tcp/8001" in str(peer_info.addrs[0])

            print("✅ Service info extraction test successful!")
            print(f"   Extracted peer ID: {peer_info.peer_id}")
            print(f"   Extracted addresses: {[str(addr) for addr in peer_info.addrs]}")

        finally:
            zeroconf.close()
