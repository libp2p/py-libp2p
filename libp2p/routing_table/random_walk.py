import asyncio
import logging
import secrets
import time
from typing import Optional, List, Callable, Dict, Any, AsyncContextManager
from contextlib import asynccontextmanager

import trio

from libp2p.abc import IHost
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import PeerInfo
from libp2p.routing_table.exceptions import RandomWalkError, PeerValidationError
from libp2p.routing_table.config import (
    RANDOM_WALK_CONCURRENCY,
    REFRESH_QUERY_TIMEOUT,
    PEER_PING_TIMEOUT
)

logger = logging.getLogger("libp2p.routing_table.random_walk")

class RandomWalk:
    """
    Random Walk implementation for peer discovery in Kademlia DHT.
    
    Generates random peer IDs and performs FIND_NODE queries to discover
    new peers and populate the routing table.
    """
    
    def __init__(
        self,
        host: IHost,
        local_peer_id: ID,
        query_function: Callable[[str], AsyncContextManager[List[PeerInfo]]],
        validation_function: Optional[Callable[[PeerInfo], AsyncContextManager[bool]]] = None,
        ping_function: Optional[Callable[[ID], AsyncContextManager[bool]]] = None,
    ):
        """
        Initialize Random Walk module.
        
        Args:
            host: The libp2p host instance
            local_peer_id: Local peer ID
            query_function: Function to perform FIND_NODE queries
            validation_function: Function to validate discovered peers (optional)
            ping_function: Function to ping peers for liveness (optional)
        """
        self.host = host
        self.local_peer_id = local_peer_id
        self.query_function = query_function
        self.validation_function = validation_function
        self.ping_function = ping_function
        
        self._running = False
        self._nursery_manager: Optional[trio.Nursery] = None
        
    def generate_random_peer_id(self) -> str:
        """
        Generate a completely random peer ID for random walk queries.
        
        Returns:
            Random peer ID as string
        """
        # Generate 32 random bytes (256 bits) - same as go-libp2p
        random_bytes = secrets.token_bytes(32)
        # Convert to hex string for query
        return random_bytes.hex()
    
    async def validate_peer(self, peer_info: PeerInfo) -> bool:
        """
        Validate a discovered peer using the same validation as bootstrap module.
        
        Args:
            peer_info: Peer information to validate
            
        Returns:
            True if peer is valid, False otherwise
        """
        try:
            # Use provided validation function if available
            if self.validation_function:
                async with self.validation_function(peer_info) as is_valid:
                    return is_valid
            
            # Default validation - basic connectivity check
            if self.ping_function:
                async with self.ping_function(peer_info.peer_id) as is_alive:
                    return is_alive
                    
            # Fallback - just check if we can connect
            try:
                with trio.move_on_after(PEER_PING_TIMEOUT):
                    await self.host.connect(peer_info)
                    return True
            except Exception as e:
                logger.debug(f"Failed to connect to peer {peer_info.peer_id}: {e}")
                return False
                
        except Exception as e:
            logger.warning(f"Peer validation failed for {peer_info.peer_id}: {e}")
            return False
    
    async def perform_random_walk(self) -> List[PeerInfo]:
        """
        Perform a single random walk operation.
        
        Returns:
            List of validated peers discovered during the walk
        """
        try:
            # Generate random peer ID
            random_peer_id = self.generate_random_peer_id()
            logger.info(f"Starting random walk for peer ID: {random_peer_id}")
            
            # Perform FIND_NODE query
            discovered_peers: List[PeerInfo] = []
            
            with trio.move_on_after(REFRESH_QUERY_TIMEOUT):
                async with self.query_function(random_peer_id) as query_result:
                    discovered_peers = query_result or []
            
            if not discovered_peers:
                logger.debug(f"No peers discovered in random walk for {random_peer_id}")
                return []
            
            logger.debug(f"Discovered {len(discovered_peers)} peers in random walk")
            
            # Validate discovered peers
            validated_peers: List[PeerInfo] = []
            
            async def validate_single_peer(peer_info: PeerInfo):
                if await self.validate_peer(peer_info):
                    validated_peers.append(peer_info)
                    logger.debug(f"Validated peer: {peer_info.peer_id}")
                else:
                    logger.debug(f"Peer validation failed: {peer_info.peer_id}")
            
            # Validate peers concurrently
            async with trio.open_nursery() as nursery:
                for peer_info in discovered_peers:
                    nursery.start_soon(validate_single_peer, peer_info)
            
            logger.info(f"Random walk completed: {len(validated_peers)}/{len(discovered_peers)} peers validated")
            return validated_peers
            
        except Exception as e:
            logger.error(f"Random walk failed: {e}")
            raise RandomWalkError(f"Random walk operation failed: {e}") from e
    
    async def run_concurrent_random_walks(self, count: int = RANDOM_WALK_CONCURRENCY) -> List[PeerInfo]:
        """
        Run multiple random walks concurrently.
        
        Args:
            count: Number of concurrent random walks to perform
            
        Returns:
            Combined list of all validated peers discovered
        """
        all_validated_peers: List[PeerInfo] = []
        logger.info(f"Starting {count} concurrent random walks")
        
        async def single_walk():
            try:
                peers = await self.perform_random_walk()
                all_validated_peers.extend(peers)
            except Exception as e:
                logger.warning(f"Concurrent random walk failed: {e}")
        
        # Run concurrent random walks
        async with trio.open_nursery() as nursery:
            for _ in range(count):
                nursery.start_soon(single_walk)
        
        # Remove duplicates based on peer ID
        unique_peers = {}
        for peer in all_validated_peers:
            unique_peers[peer.peer_id] = peer
        
        result = list(unique_peers.values())
        logger.info(f"Concurrent random walks completed: {len(result)} unique peers discovered")
        return result
