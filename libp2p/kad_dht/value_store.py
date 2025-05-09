"""
Value store implementation for Kademlia DHT.

Provides a way to store and retrieve key-value pairs with optional expiration.
"""

import logging
import time
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("libp2p.kademlia.value_store")

# Default time to live for values in seconds (24 hours)
DEFAULT_TTL = 24 * 60 * 60


class ValueStore:
    """
    Store for key-value pairs in a Kademlia DHT.
    
    Values are stored with a timestamp and optional expiration time.
    """
    
    def __init__(self):
        """Initialize an empty value store."""
        # Store format: {key: (value, timestamp, expiration_time)}
        self.store: Dict[bytes, Tuple[bytes, float, Optional[float]]] = {}
        
    def put(self, key: bytes, value: bytes, ttl: Optional[int] = None) -> None:
        """
        Store a value in the DHT.
        
        Args:
            key: The key to store the value under
            value: The value to store
            ttl: Time to live in seconds, or None for no expiration
        """
        timestamp = time.time()
        expiration = None if ttl is None else timestamp + ttl
        self.store[key] = (value, timestamp, expiration)
        logger.debug(f"Stored value for key {key.hex()[:8]}...")
        
    def get(self, key: bytes) -> Optional[bytes]:
        """
        Retrieve a value from the DHT.
        
        Args:
            key: The key to look up
            
        Returns:
            Optional[bytes]: The stored value, or None if not found or expired
        """
        if key not in self.store:
            return None
            
        value, timestamp, expiration = self.store[key]
        
        # Check if the value has expired
        if expiration is not None and time.time() > expiration:
            self.remove(key)
            return None
            
        return value
        
    def remove(self, key: bytes) -> bool:
        """
        Remove a value from the DHT.
        
        Args:
            key: The key to remove
            
        Returns:
            bool: True if the key was found and removed, False otherwise
        """
        if key in self.store:
            del self.store[key]
            logger.debug(f"Removed value for key {key.hex()[:8]}...")
            return True
        return False
        
    def has(self, key: bytes) -> bool:
        """
        Check if a key exists in the store and hasn't expired.
        
        Args:
            key: The key to check
            
        Returns:
            bool: True if the key exists and hasn't expired, False otherwise
        """
        if key not in self.store:
            return False
            
        _, _, expiration = self.store[key]
        if expiration is not None and time.time() > expiration:
            self.remove(key)
            return False
            
        return True
        
    def cleanup_expired(self) -> int:
        """
        Remove all expired values from the store.
        
        Returns:
            int: The number of expired values that were removed
        """
        current_time = time.time()
        expired_keys = [
            key for key, (_, _, exp) in self.store.items()
            if exp is not None and current_time > exp
        ]
        
        for key in expired_keys:
            del self.store[key]
            
        if expired_keys:
            logger.debug(f"Cleaned up {len(expired_keys)} expired values")
            
        return len(expired_keys)
        
    def get_keys(self) -> list[bytes]:
        """
        Get all non-expired keys in the store.
        
        Returns:
            list[bytes]: List of keys
        """
        # Clean up expired values first
        self.cleanup_expired()
        return list(self.store.keys())
        
    def size(self) -> int:
        """
        Get the number of items in the store (after removing expired entries).
        
        Returns:
            int: Number of items
        """
        self.cleanup_expired()
        return len(self.store)