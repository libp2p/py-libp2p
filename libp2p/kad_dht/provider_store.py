"""
Provider record storage for Kademlia DHT.

This module implements the storage for content provider records in the Kademlia DHT.
"""

import time
import logging
from typing import Dict, List, Set, Optional, Tuple

from libp2p.peer.id import ID
from libp2p.peer.peerinfo import PeerInfo

logger = logging.getLogger("libp2p.kademlia.provider_store")

# Constants for provider records (based on IPFS standards)
PROVIDER_RECORD_REPUBLISH_INTERVAL = 22 * 60 * 60  # 22 hours in seconds
PROVIDER_RECORD_EXPIRATION_INTERVAL = 48 * 60 * 60  # 48 hours in seconds
PROVIDER_ADDRESS_TTL = 30 * 60  # 30 minutes in seconds


class ProviderRecord:
    """
    A record for a content provider in the DHT.
    
    Contains the peer ID, network addresses (optional), and timestamp.
    """
    
    def __init__(self, peer_id: ID, addresses: Optional[List] = None, timestamp: float = None):
        """
        Initialize a new provider record.
        
        Args:
            peer_id: The ID of the provider peer
            addresses: Optional network addresses of the provider peer
            timestamp: Time this record was created/updated (defaults to current time)
        """
        self.peer_id = peer_id
        self.addresses = addresses or []
        self.timestamp = timestamp or time.time()
        self.addresses_expiry = self.timestamp + PROVIDER_ADDRESS_TTL


class ProviderStore:
    """
    Store for content provider records in the Kademlia DHT.
    
    Maps content keys to provider records, with support for expiration.
    """
    
    def __init__(self):
        """Initialize a new provider store."""
        # Maps content keys to a dict of provider records (peer_id -> record)
        self.providers: Dict[bytes, Dict[str, ProviderRecord]] = {}
        
    def add_provider(self, key: bytes, provider: PeerInfo) -> None:
        """
        Add a provider for a given content key.
        
        Args:
            key: The content key
            provider: The provider's peer information
        """
        # Initialize providers for this key if needed
        if key not in self.providers:
            self.providers[key] = {}
        
        # Add or update the provider record
        peer_id_str = str(provider.peer_id)  # Use string representation as dict key
        self.providers[key][peer_id_str] = ProviderRecord(
            peer_id=provider.peer_id,
            addresses=provider.addrs,
            timestamp=time.time()
        )
        logger.debug(f"Added provider {provider.peer_id} for key {key.hex()}")
        
    def get_providers(self, key: bytes) -> List[PeerInfo]:
        """
        Get all providers for a given content key.
        
        Args:
            key: The content key
            
        Returns:
            List[PeerInfo]: List of providers for the key
        """
        if key not in self.providers:
            return []
            
        # Collect valid provider records (not expired)
        result = []
        current_time = time.time()
        expired_peers = []
        
        for peer_id_str, record in self.providers[key].items():
            # Check if the record has expired
            if current_time - record.timestamp > PROVIDER_RECORD_EXPIRATION_INTERVAL:
                expired_peers.append(peer_id_str)
                continue
                
            # Use addresses only if they haven't expired
            addresses = []
            if current_time - record.timestamp <= PROVIDER_ADDRESS_TTL:
                addresses = record.addresses
                
            # Create PeerInfo and add to results
            result.append(PeerInfo(record.peer_id, addresses))
            
        # Clean up expired records
        for peer_id in expired_peers:
            del self.providers[key][peer_id]
            
        # Remove the key if no providers left
        if not self.providers[key]:
            del self.providers[key]
            
        return result
        
    def cleanup_expired(self) -> None:
        """Remove expired provider records."""
        current_time = time.time()
        expired_keys = []
        
        for key, providers in self.providers.items():
            expired_providers = []
            
            for peer_id_str, record in providers.items():
                if current_time - record.timestamp > PROVIDER_RECORD_EXPIRATION_INTERVAL:
                    expired_providers.append(peer_id_str)
                    logger.debug(f"Removing expired provider {peer_id_str} for key {key.hex()}")
            
            # Remove expired providers
            for peer_id in expired_providers:
                del providers[peer_id]
                
            # Track empty keys for removal
            if not providers:
                expired_keys.append(key)
                
        # Remove empty keys
        for key in expired_keys:
            del self.providers[key]
            logger.debug(f"Removed key with no providers: {key.hex()}")
            
    def get_provided_keys(self, peer_id: ID) -> List[bytes]:
        """
        Get all content keys provided by a specific peer.
        
        Args:
            peer_id: The peer ID to look for
            
        Returns:
            List[bytes]: List of content keys provided by the peer
        """
        peer_id_str = str(peer_id)
        result = []
        
        for key, providers in self.providers.items():
            if peer_id_str in providers:
                result.append(key)
                
        return result
        
    def size(self) -> int:
        """
        Get the number of content keys in the provider store.
        
        Returns:
            int: Number of content keys
        """
        return len(self.providers)