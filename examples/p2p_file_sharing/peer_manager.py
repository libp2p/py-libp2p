"""
Peer management for P2P file sharing.

This module provides peer discovery, persistence, and reconnection capabilities
using the peerstore and various discovery mechanisms.
"""

import asyncio
import json
import logging
import os
import time
from typing import Dict, List, Optional, Set

import trio

from libp2p.abc import IHost, IPeerStore
from libp2p.discovery.bootstrap.bootstrap import BootstrapDiscovery
from libp2p.discovery.mdns.mdns import MDNSDiscovery
from libp2p.discovery.rendezvous.discovery import RendezvousDiscovery
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import PeerInfo

logger = logging.getLogger("libp2p.file_sharing.peer_manager")


class PeerManager:
    """
    Manages peer discovery, persistence, and reconnection for file sharing.
    
    This class coordinates multiple discovery mechanisms and maintains
    a persistent peer database for reliable peer-to-peer connections.
    """

    def __init__(self, host: IHost, peer_db_path: str = "./peer_database.json"):
        """
        Initialize peer manager.

        Args:
            host: The libp2p host instance
            peer_db_path: Path to persistent peer database file
        """
        self.host = host
        self.peerstore: IPeerStore = host.get_peerstore()
        self.peer_db_path = peer_db_path
        
        # Discovery mechanisms
        self.mdns_discovery: Optional[MDNSDiscovery] = None
        self.bootstrap_discovery: Optional[BootstrapDiscovery] = None
        self.rendezvous_discovery: Optional[RendezvousDiscovery] = None
        
        # Peer tracking
        self.known_peers: Dict[ID, Dict] = {}
        self.connected_peers: Set[ID] = set()
        self.failed_peers: Set[ID] = set()
        
        # Discovery settings
        self.discovery_namespace = "p2p-file-sharing"
        self.bootstrap_nodes = [
            "/ip4/104.131.131.82/tcp/4001/p2p/QmaCpDMGvV2BGHeYERUEnRQAwe3N8SzbUtfsmvsqQLuvuJ",
            "/ip4/104.131.131.82/udp/4001/quic/p2p/QmaCpDMGvV2BGHeYERUEnRQAwe3N8SzbUtfsmvsqQLuvuJ",
        ]
        
        # Load persistent peer database
        self._load_peer_database()

    def _load_peer_database(self) -> None:
        """Load peer database from persistent storage."""
        if not os.path.exists(self.peer_db_path):
            logger.info("No existing peer database found, starting fresh")
            return
        
        try:
            with open(self.peer_db_path, 'r') as f:
                data = json.load(f)
                
            for peer_id_str, peer_data in data.items():
                try:
                    peer_id = ID.from_base58(peer_id_str)
                    self.known_peers[peer_id] = peer_data
                    
                    # Add to peerstore if not expired
                    if not self._is_peer_expired(peer_data):
                        addrs = peer_data.get('addrs', [])
                        ttl = peer_data.get('ttl', 3600)
                        self.peerstore.add_addrs(peer_id, addrs, ttl)
                        
                except Exception as e:
                    logger.warning(f"Failed to load peer {peer_id_str}: {e}")
            
            logger.info(f"Loaded {len(self.known_peers)} peers from database")
            
        except Exception as e:
            logger.error(f"Failed to load peer database: {e}")

    def _save_peer_database(self) -> None:
        """Save peer database to persistent storage."""
        try:
            # Convert peer data to JSON-serializable format
            data = {}
            for peer_id, peer_data in self.known_peers.items():
                peer_data_copy = peer_data.copy()
                # Convert multiaddrs to strings
                if 'addrs' in peer_data_copy:
                    peer_data_copy['addrs'] = [str(addr) for addr in peer_data_copy['addrs']]
                data[peer_id.to_base58()] = peer_data_copy
            
            # Write to file atomically
            temp_path = self.peer_db_path + ".tmp"
            with open(temp_path, 'w') as f:
                json.dump(data, f, indent=2)
            
            os.rename(temp_path, self.peer_db_path)
            logger.debug("Peer database saved")
            
        except Exception as e:
            logger.error(f"Failed to save peer database: {e}")

    def _is_peer_expired(self, peer_data: Dict) -> bool:
        """Check if peer data is expired."""
        last_seen = peer_data.get('last_seen', 0)
        ttl = peer_data.get('ttl', 3600)
        return time.time() - last_seen > ttl

    async def initialize_discovery(self) -> None:
        """Initialize peer discovery mechanisms."""
        logger.info("Initializing peer discovery mechanisms...")
        
        # Initialize mDNS discovery for local network
        try:
            self.mdns_discovery = MDNSDiscovery(self.host.get_network(), port=8000)
            self.mdns_discovery.start()
            logger.info("mDNS discovery initialized")
        except Exception as e:
            logger.warning(f"Failed to initialize mDNS discovery: {e}")
        
        # Initialize bootstrap discovery
        try:
            self.bootstrap_discovery = BootstrapDiscovery(
                self.host.get_network(),
                self.bootstrap_nodes
            )
            await self.bootstrap_discovery.start()
            logger.info("Bootstrap discovery initialized")
        except Exception as e:
            logger.warning(f"Failed to initialize bootstrap discovery: {e}")
        
        # Initialize rendezvous discovery
        try:
            # This would require a rendezvous server
            # For now, we'll skip it
            logger.info("Rendezvous discovery not configured")
        except Exception as e:
            logger.warning(f"Failed to initialize rendezvous discovery: {e}")

    async def shutdown_discovery(self) -> None:
        """Shutdown peer discovery mechanisms."""
        logger.info("Shutting down peer discovery mechanisms...")
        
        if self.mdns_discovery:
            self.mdns_discovery.stop()
        
        if self.bootstrap_discovery:
            await self.bootstrap_discovery.stop()
        
        if self.rendezvous_discovery:
            await self.rendezvous_discovery.stop()
        
        # Save peer database
        self._save_peer_database()
        
        logger.info("Peer discovery mechanisms shut down")

    def add_peer(self, peer_info: PeerInfo, ttl: int = 3600) -> None:
        """
        Add a peer to the known peers list.
        
        Args:
            peer_info: Information about the peer
            ttl: Time-to-live for peer information in seconds
        """
        peer_id = peer_info.peer_id
        
        # Add to peerstore
        self.peerstore.add_addrs(peer_id, peer_info.addrs, ttl)
        
        # Add to known peers
        self.known_peers[peer_id] = {
            'addrs': peer_info.addrs,
            'last_seen': time.time(),
            'ttl': ttl,
            'connection_attempts': 0,
            'last_connection_attempt': 0,
            'successful_connections': 0
        }
        
        logger.info(f"Added peer: {peer_id}")
        self._save_peer_database()

    def remove_peer(self, peer_id: ID) -> None:
        """Remove a peer from known peers."""
        if peer_id in self.known_peers:
            del self.known_peers[peer_id]
            self.peerstore.clear_peerdata(peer_id)
            logger.info(f"Removed peer: {peer_id}")
            self._save_peer_database()

    def get_known_peers(self) -> List[PeerInfo]:
        """Get list of known peers."""
        peers = []
        for peer_id, peer_data in self.known_peers.items():
            if not self._is_peer_expired(peer_data):
                try:
                    peer_info = self.peerstore.peer_info(peer_id)
                    peers.append(peer_info)
                except Exception as e:
                    logger.debug(f"Failed to get peer info for {peer_id}: {e}")
        
        return peers

    def get_connected_peers(self) -> List[ID]:
        """Get list of currently connected peers."""
        return list(self.connected_peers)

    def get_failed_peers(self) -> List[ID]:
        """Get list of peers that failed to connect."""
        return list(self.failed_peers)

    async def connect_to_peer(self, peer_id: ID) -> bool:
        """
        Attempt to connect to a known peer.
        
        Args:
            peer_id: ID of the peer to connect to
            
        Returns:
            True if connection successful, False otherwise
        """
        if peer_id in self.connected_peers:
            return True
        
        try:
            # Get peer info from peerstore
            peer_info = self.peerstore.peer_info(peer_id)
            
            # Update connection attempt tracking
            if peer_id in self.known_peers:
                self.known_peers[peer_id]['connection_attempts'] += 1
                self.known_peers[peer_id]['last_connection_attempt'] = time.time()
            
            # Attempt connection
            await self.host.connect(peer_info)
            
            # Connection successful
            self.connected_peers.add(peer_id)
            self.failed_peers.discard(peer_id)
            
            if peer_id in self.known_peers:
                self.known_peers[peer_id]['successful_connections'] += 1
                self.known_peers[peer_id]['last_seen'] = time.time()
            
            logger.info(f"Successfully connected to peer: {peer_id}")
            self._save_peer_database()
            return True
            
        except Exception as e:
            logger.warning(f"Failed to connect to peer {peer_id}: {e}")
            self.failed_peers.add(peer_id)
            self.connected_peers.discard(peer_id)
            return False

    async def reconnect_failed_peers(self) -> None:
        """Attempt to reconnect to previously failed peers."""
        logger.info("Attempting to reconnect to failed peers...")
        
        failed_peers = list(self.failed_peers)
        for peer_id in failed_peers:
            # Check if enough time has passed since last attempt
            if peer_id in self.known_peers:
                last_attempt = self.known_peers[peer_id].get('last_connection_attempt', 0)
                if time.time() - last_attempt < 60:  # Wait at least 1 minute
                    continue
            
            # Attempt reconnection
            if await self.connect_to_peer(peer_id):
                logger.info(f"Successfully reconnected to peer: {peer_id}")
            else:
                logger.debug(f"Reconnection failed for peer: {peer_id}")

    async def maintain_connections(self) -> None:
        """Maintain connections to known peers."""
        logger.info("Maintaining peer connections...")
        
        known_peers = self.get_known_peers()
        for peer_info in known_peers:
            peer_id = peer_info.peer_id
            
            # Skip if already connected
            if peer_id in self.connected_peers:
                continue
            
            # Attempt connection
            await self.connect_to_peer(peer_id)
            
            # Small delay between connection attempts
            await trio.sleep(0.1)

    def get_peer_stats(self) -> Dict[str, int]:
        """Get peer statistics."""
        return {
            "known_peers": len(self.known_peers),
            "connected_peers": len(self.connected_peers),
            "failed_peers": len(self.failed_peers),
            "expired_peers": len([
                p for p in self.known_peers.values() 
                if self._is_peer_expired(p)
            ])
        }

    async def cleanup_expired_peers(self) -> None:
        """Remove expired peers from the database."""
        expired_peers = []
        for peer_id, peer_data in self.known_peers.items():
            if self._is_peer_expired(peer_data):
                expired_peers.append(peer_id)
        
        for peer_id in expired_peers:
            self.remove_peer(peer_id)
        
        if expired_peers:
            logger.info(f"Cleaned up {len(expired_peers)} expired peers")

    async def start_peer_maintenance(self) -> None:
        """Start background peer maintenance tasks."""
        logger.info("Starting peer maintenance tasks...")
        
        async def maintenance_loop():
            while True:
                try:
                    # Clean up expired peers
                    await self.cleanup_expired_peers()
                    
                    # Attempt to reconnect failed peers
                    await self.reconnect_failed_peers()
                    
                    # Maintain connections to known peers
                    await self.maintain_connections()
                    
                    # Save peer database
                    self._save_peer_database()
                    
                    # Wait before next maintenance cycle
                    await trio.sleep(300)  # 5 minutes
                    
                except Exception as e:
                    logger.error(f"Error in peer maintenance: {e}")
                    await trio.sleep(60)  # Wait 1 minute on error
        
        # Start maintenance task
        trio.start_soon(maintenance_loop)
