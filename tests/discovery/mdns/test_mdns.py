"""
Integration test for mDNS discovery where one host finds another.
"""
import time
import socket
import pytest
from zeroconf import Zeroconf

from libp2p.discovery.mdns.broadcaster import PeerBroadcaster
from libp2p.discovery.mdns.listener import PeerListener
from libp2p.peer.id import ID
from libp2p.peer.peerstore import PeerStore


class TestMDNSDiscovery:
    """Integration test for mDNS peer discovery."""

    def test_one_host_finds_another(self):
        """Test that one host can find another host using mDNS."""
        # Create two separate Zeroconf instances to simulate different hosts
        host1_zeroconf = Zeroconf()
        host2_zeroconf = Zeroconf()
        
        try:
            # Host 1: Set up as broadcaster (the host to be discovered)
            host1_peer_id_obj = ID.from_base58("QmNnooDu7bfjPFoTZYxMNLWUQJyrVwtbZg5gBMjTezGAJN")
            host1_peer_id = str(host1_peer_id_obj)  # Convert to string
            host1_broadcaster = PeerBroadcaster(
                zeroconf=host1_zeroconf,
                service_type="_p2p._udp.local.",
                service_name="host1._p2p._udp.local.",
                peer_id=host1_peer_id,
                port=8000
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
            
            
            # Manually trigger discovery by calling add_service
            # This simulates what happens when mDNS discovers a service
            host2_listener.add_service(
                host1_zeroconf,  # Use host1's zeroconf so it can find the service
                "_p2p._udp.local.",
                "host1._p2p._udp.local."
            )
            
            # Verify that host2 discovered host1
            assert len(host2_listener.discovered_services) > 0
            assert "host1._p2p._udp.local." in host2_listener.discovered_services
            
            # Verify that host1's peer info was added to host2's peerstore
            discovered_peer_id = host2_listener.discovered_services["host1._p2p._udp.local."]
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
            
            print(f"✅ Host2 successfully discovered Host1!")
            print(f"   Discovered peer ID: {discovered_peer_id}")
            print(f"   Discovered addresses: {[str(addr) for addr in addrs]}")
            
            # Clean up
            host1_broadcaster.unregister()
            host2_listener.stop()
            
        finally:
            host1_zeroconf.close()
            host2_zeroconf.close()

    def test_peer_discovery_with_multiple_addresses(self):
        """Test discovery works with peers having multiple IP addresses."""
        host1_zeroconf = Zeroconf()
        host2_zeroconf = Zeroconf()
        
        try:
            # Create a peer with multiple addresses
            host1_peer_id_obj = ID.from_base58("QmYyQSo1c1Ym7orWxLYvCrM2EmxFTANf8wXmmE7DWjhx5N")
            host1_peer_id = str(host1_peer_id_obj)  # Convert to string
            
            # Manually create service info with multiple addresses
            from zeroconf import ServiceInfo
            hostname = socket.gethostname()
            
            service_info = ServiceInfo(
                type_="_p2p._udp.local.",
                name="multi-addr-host._p2p._udp.local.",
                port=8001,
                properties={b"id": host1_peer_id.encode()},
                server=f"{hostname}.local.",
                addresses=[
                    socket.inet_aton("192.168.1.100"),
                    socket.inet_aton("10.0.0.50"),
                ],
            )
            
            # Register the service
            host1_zeroconf.register_service(service_info)
            
            # Set up listener
            host2_peerstore = PeerStore()
            host2_listener = PeerListener(
                peerstore=host2_peerstore,
                zeroconf=host2_zeroconf,
                service_type="_p2p._udp.local.",
                service_name="host2._p2p._udp.local.",
            )
            
            # Trigger discovery
            host2_listener.add_service(
                host1_zeroconf,
                "_p2p._udp.local.",
                "multi-addr-host._p2p._udp.local."
            )
            
            # Verify discovery
            assert "multi-addr-host._p2p._udp.local." in host2_listener.discovered_services
            discovered_peer_id = host2_listener.discovered_services["multi-addr-host._p2p._udp.local."]
            
            # Check multiple addresses were discovered
            addrs = host2_peerstore.addrs(discovered_peer_id)
            assert len(addrs) == 2
            
            addr_strings = [str(addr) for addr in addrs]
            assert "/ip4/192.168.1.100/tcp/8001" in addr_strings
            assert "/ip4/10.0.0.50/tcp/8001" in addr_strings
            
            print(f"✅ Successfully discovered peer with multiple addresses!")
            print(f"   Addresses: {addr_strings}")
            
            # Clean up
            host2_listener.stop()
            
        finally:
            host1_zeroconf.close()
            host2_zeroconf.close()
