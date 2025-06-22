"""
Basic integration tests for mDNS components.
"""
import socket
import pytest
from zeroconf import ServiceInfo, Zeroconf

from libp2p.discovery.mdns.broadcaster import PeerBroadcaster
from libp2p.discovery.mdns.listener import PeerListener
from libp2p.peer.id import ID
from libp2p.peer.peerstore import PeerStore


class TestMDNSIntegration:
    """Basic integration tests for mDNS components."""

    def test_broadcaster_listener_basic_integration(self):
        """Test basic broadcaster and listener integration with actual service discovery."""
        import time
        
        # Create two separate Zeroconf instances
        zeroconf1 = Zeroconf()
        zeroconf2 = Zeroconf()
        
        try:
            # Set up broadcaster
            broadcaster_peer_id_obj = ID.from_base58("QmNnooDu7bfjPFoTZYxMNLWUQJyrVwtbZg5gBMjTezGAJN")
            broadcaster_peer_id = str(broadcaster_peer_id_obj)  # Convert to string
            broadcaster = PeerBroadcaster(
                zeroconf=zeroconf1,
                service_type="_p2p._udp.local.",
                service_name="broadcaster-peer._p2p._udp.local.",
                peer_id=broadcaster_peer_id,
                port=8000
            )
            
            # Set up listener
            peerstore = PeerStore()
            listener = PeerListener(
                peerstore=peerstore,
                zeroconf=zeroconf2,
                service_type="_p2p._udp.local.",
                service_name="listener-peer._p2p._udp.local.",
            )
            
            # Verify initial state
            assert broadcaster.service_info is not None
            assert listener.discovered_services == {}
            assert len(peerstore.peer_ids()) == 0
            
            # Broadcaster registers its service
            broadcaster.register()
            
            # Simulate discovery - listener discovers the broadcaster's service
            listener.add_service(
                zeroconf1,  # Use broadcaster's zeroconf to find the service
                "_p2p._udp.local.",
                "broadcaster-peer._p2p._udp.local."
            )
            
            # Verify that the listener discovered the broadcaster
            assert len(listener.discovered_services) > 0
            assert "broadcaster-peer._p2p._udp.local." in listener.discovered_services
            
            # Verify the discovered peer ID matches what was broadcast
            discovered_peer_id = listener.discovered_services["broadcaster-peer._p2p._udp.local."]
            assert str(discovered_peer_id) == broadcaster_peer_id
            
            # Verify the peer was added to the peerstore
            assert len(peerstore.peer_ids()) > 0
            assert discovered_peer_id in peerstore.peer_ids()
            
            # Verify the addresses were correctly stored
            addrs = peerstore.addrs(discovered_peer_id)
            assert len(addrs) > 0
            # Should be TCP since we always use TCP protocol
            assert "/tcp/8000" in str(addrs[0])
            
            print(f"✅ Integration test successful!")
            print(f"   Broadcaster peer ID: {broadcaster_peer_id}")
            print(f"   Discovered peer ID: {discovered_peer_id}")
            print(f"   Discovered addresses: {[str(addr) for addr in addrs]}")
            
            # Clean up
            broadcaster.unregister()
            
        finally:
            zeroconf1.close()
            zeroconf2.close()

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
            test_peer_id = ID.from_base58("QmYyQSo1c1Ym7orWxLYvCrM2EmxFTANf8wXmmE7DWjhx5N")
            hostname = socket.gethostname()
            
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
            
            # Clean up
            
        finally:
            zeroconf.close()
