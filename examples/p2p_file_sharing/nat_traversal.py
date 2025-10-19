"""
NAT traversal utilities for P2P file sharing.

This module provides NAT traversal capabilities using Circuit Relay v2,
AutoNAT, and DCUtR (Direct Connection Upgrade through Relay) to enable
file sharing across NATs and firewalls.
"""

import asyncio
import logging
import time
from typing import Dict, List, Optional, Set

import trio

from libp2p.abc import IHost
from libp2p.host.autonat.autonat import AutoNATService, AutoNATStatus
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import PeerInfo
from libp2p.relay.circuit_v2.dcutr import DCUtRProtocol
from libp2p.relay.circuit_v2.discovery import RelayDiscovery
from libp2p.relay.circuit_v2.protocol import CircuitV2Protocol

logger = logging.getLogger("libp2p.file_sharing.nat_traversal")


class NATTraversalManager:
    """
    Manages NAT traversal for P2P file sharing.
    
    This class coordinates AutoNAT, Circuit Relay v2, and DCUtR to provide
    robust connectivity across NATs and firewalls.
    """

    def __init__(self, host: IHost):
        """
        Initialize NAT traversal manager.

        Args:
            host: The libp2p host instance
        """
        self.host = host
        self.autonat_service: Optional[AutoNATService] = None
        self.relay_discovery: Optional[RelayDiscovery] = None
        self.circuit_v2_protocol: Optional[CircuitV2Protocol] = None
        self.dcutr_protocol: Optional[DCUtRProtocol] = None
        
        # Track discovered relays
        self.discovered_relays: Set[ID] = set()
        self.nat_status = AutoNATStatus.UNKNOWN
        
        # Connection statistics
        self.direct_connections: Set[ID] = set()
        self.relay_connections: Set[ID] = set()
        self.failed_connections: Set[ID] = set()

    async def initialize(self) -> None:
        """Initialize NAT traversal services."""
        logger.info("Initializing NAT traversal services...")
        
        # Initialize AutoNAT service
        self.autonat_service = AutoNATService(self.host)
        self.host.set_stream_handler(
            self.autonat_service.AUTONAT_PROTOCOL_ID,
            self.autonat_service.handle_stream
        )
        
        # Initialize Circuit Relay v2 protocol
        self.circuit_v2_protocol = CircuitV2Protocol(self.host)
        await self.circuit_v2_protocol.start()
        
        # Initialize DCUtR protocol for hole punching
        self.dcutr_protocol = DCUtRProtocol(self.host)
        await self.dcutr_protocol.start()
        
        # Initialize relay discovery
        self.relay_discovery = RelayDiscovery(self.host)
        await self.relay_discovery.start()
        
        logger.info("NAT traversal services initialized")

    async def shutdown(self) -> None:
        """Shutdown NAT traversal services."""
        logger.info("Shutting down NAT traversal services...")
        
        if self.circuit_v2_protocol:
            await self.circuit_v2_protocol.stop()
        
        if self.dcutr_protocol:
            await self.dcutr_protocol.stop()
        
        if self.relay_discovery:
            await self.relay_discovery.stop()
        
        logger.info("NAT traversal services shut down")

    async def determine_nat_status(self) -> AutoNATStatus:
        """
        Determine the NAT status of this node.
        
        Returns:
            The NAT status (PUBLIC, PRIVATE, or UNKNOWN)
        """
        if not self.autonat_service:
            return AutoNATStatus.UNKNOWN
        
        # Try to determine NAT status by attempting connections
        connected_peers = self.host.get_connected_peers()
        if not connected_peers:
            logger.warning("No connected peers available for NAT status determination")
            return AutoNATStatus.UNKNOWN
        
        # Use the first connected peer for NAT status check
        test_peer = list(connected_peers)[0]
        
        try:
            # This is a simplified NAT status check
            # In a real implementation, you would use the AutoNAT protocol
            # to request other peers to dial back to you
            
            # For now, we'll assume we're behind NAT if we have no public addresses
            listen_addrs = self.host.get_addrs()
            has_public_addr = any(
                not self._is_private_address(str(addr)) 
                for addr in listen_addrs
            )
            
            if has_public_addr:
                self.nat_status = AutoNATStatus.PUBLIC
            else:
                self.nat_status = AutoNATStatus.PRIVATE
                
        except Exception as e:
            logger.error(f"Error determining NAT status: {e}")
            self.nat_status = AutoNATStatus.UNKNOWN
        
        logger.info(f"NAT status determined: {self.nat_status}")
        return self.nat_status

    def _is_private_address(self, addr_str: str) -> bool:
        """Check if an address is private/local."""
        private_prefixes = [
            "/ip4/127.",  # localhost
            "/ip4/10.",   # private class A
            "/ip4/172.",  # private class B (partial)
            "/ip4/192.168.",  # private class C
            "/ip6/::1",   # IPv6 localhost
            "/ip6/fe80:", # IPv6 link-local
        ]
        
        return any(addr_str.startswith(prefix) for prefix in private_prefixes)

    async def discover_relays(self) -> List[ID]:
        """
        Discover available relay nodes.
        
        Returns:
            List of discovered relay peer IDs
        """
        if not self.relay_discovery:
            return []
        
        # Trigger relay discovery
        await self.relay_discovery.discover_relays()
        
        # Get discovered relays
        discovered = set(self.relay_discovery.get_discovered_relays())
        new_relays = discovered - self.discovered_relays
        
        if new_relays:
            logger.info(f"Discovered {len(new_relays)} new relay nodes")
            self.discovered_relays.update(new_relays)
        
        return list(self.discovered_relays)

    async def connect_with_nat_traversal(self, peer_info: PeerInfo) -> bool:
        """
        Attempt to connect to a peer using NAT traversal techniques.
        
        This method tries multiple connection strategies:
        1. Direct connection
        2. DCUtR hole punching
        3. Circuit relay connection
        
        Args:
            peer_info: Information about the peer to connect to
            
        Returns:
            True if connection successful, False otherwise
        """
        peer_id = peer_info.peer_id
        logger.info(f"Attempting NAT traversal connection to peer: {peer_id}")
        
        # Strategy 1: Try direct connection first
        if await self._try_direct_connection(peer_info):
            self.direct_connections.add(peer_id)
            logger.info(f"Direct connection successful to {peer_id}")
            return True
        
        # Strategy 2: Try DCUtR hole punching
        if await self._try_dcutr_connection(peer_info):
            self.direct_connections.add(peer_id)
            logger.info(f"DCUtR connection successful to {peer_id}")
            return True
        
        # Strategy 3: Try circuit relay connection
        if await self._try_relay_connection(peer_info):
            self.relay_connections.add(peer_id)
            logger.info(f"Relay connection successful to {peer_id}")
            return True
        
        # All strategies failed
        self.failed_connections.add(peer_id)
        logger.warning(f"All connection strategies failed for peer: {peer_id}")
        return False

    async def _try_direct_connection(self, peer_info: PeerInfo) -> bool:
        """Try direct connection to peer."""
        try:
            await self.host.connect(peer_info)
            return True
        except Exception as e:
            logger.debug(f"Direct connection failed: {e}")
            return False

    async def _try_dcutr_connection(self, peer_info: PeerInfo) -> bool:
        """Try DCUtR hole punching connection."""
        if not self.dcutr_protocol:
            return False
        
        try:
            # DCUtR requires an initial relay connection
            # This is a simplified implementation
            # In practice, you would establish a relay connection first
            # then attempt hole punching
            
            # For now, we'll skip DCUtR if we don't have relays
            if not self.discovered_relays:
                return False
            
            # Attempt DCUtR connection
            # This would involve the full DCUtR protocol implementation
            logger.debug("DCUtR connection attempt (simplified)")
            return False
            
        except Exception as e:
            logger.debug(f"DCUtR connection failed: {e}")
            return False

    async def _try_relay_connection(self, peer_info: PeerInfo) -> bool:
        """Try circuit relay connection."""
        if not self.circuit_v2_protocol or not self.discovered_relays:
            return False
        
        try:
            # Select a relay node
            relay_id = list(self.discovered_relays)[0]
            
            # Create relay connection
            # This is a simplified implementation
            # In practice, you would use the Circuit Relay v2 protocol
            # to establish a relayed connection
            
            logger.debug(f"Attempting relay connection via {relay_id}")
            
            # For now, we'll simulate a relay connection
            # In a real implementation, you would:
            # 1. Connect to the relay
            # 2. Request a relayed connection to the target peer
            # 3. Use the relayed stream for communication
            
            return False
            
        except Exception as e:
            logger.debug(f"Relay connection failed: {e}")
            return False

    def get_connection_stats(self) -> Dict[str, int]:
        """Get connection statistics."""
        return {
            "direct_connections": len(self.direct_connections),
            "relay_connections": len(self.relay_connections),
            "failed_connections": len(self.failed_connections),
            "discovered_relays": len(self.discovered_relays),
            "nat_status": self.nat_status
        }

    async def optimize_connections(self) -> None:
        """Optimize existing connections by attempting direct connections."""
        logger.info("Optimizing connections...")
        
        # For each relay connection, try to establish a direct connection
        for peer_id in list(self.relay_connections):
            try:
                # Get peer info from peerstore
                peer_info = self.host.get_peerstore().peer_info(peer_id)
                
                # Try direct connection
                if await self._try_direct_connection(peer_info):
                    self.relay_connections.discard(peer_id)
                    self.direct_connections.add(peer_id)
                    logger.info(f"Upgraded relay connection to direct: {peer_id}")
                
            except Exception as e:
                logger.debug(f"Failed to optimize connection to {peer_id}: {e}")
        
        logger.info("Connection optimization completed")
