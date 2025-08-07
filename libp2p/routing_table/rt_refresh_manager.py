import asyncio
import logging
import time
from typing import Optional, List, Callable, Dict, Any, Protocol, AsyncContextManager
from contextlib import asynccontextmanager

import trio

from libp2p.abc import IHost
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import PeerInfo
from libp2p.routing_table.exceptions import RoutingTableRefreshError
from libp2p.routing_table.random_walk import RandomWalk
from libp2p.routing_table.config import (
    MIN_RT_REFRESH_THRESHOLD,
    REFRESH_INTERVAL,
    SUCCESSFUL_OUTBOUND_QUERY_GRACE_PERIOD,
    PEER_PING_TIMEOUT,
    RANDOM_WALK_ENABLED
)

logger = logging.getLogger("libp2p.routing_table.rt_refresh_manager")

class RoutingTableProtocol(Protocol):
    """Protocol defining the interface for routing table operations."""
    
    def size(self) -> int:
        """Return the current size of the routing table."""
        ...
    
    def get_peer_infos(self) -> List[PeerInfo]:
        """Get list of all peers in the routing table."""
        ...
    
    def add_peer(self, peer_info: PeerInfo) -> bool:
        """Add a peer to the routing table."""
        ...
    
    def remove_peer(self, peer_id: ID) -> None:
        """Remove a peer from the routing table."""
        ...

class RefreshTrigger:
    """Represents a refresh trigger request."""
    
    def __init__(self, force_refresh: bool = False):
        self.force_refresh = force_refresh
        self.response_channel: Optional[trio.MemorySendChannel] = None
        self.response_receive_channel: Optional[trio.MemoryReceiveChannel] = None

class RTRefreshManager:
    """
    Routing Table Refresh Manager for py-libp2p.
    
    Manages periodic routing table refreshes and random walk operations
    to maintain routing table health and discover new peers.
    """
    
    def __init__(
        self,
        host: IHost,
        routing_table: RoutingTableProtocol,
        local_peer_id: ID,
        query_function: Callable[[str], AsyncContextManager[List[PeerInfo]]],
        ping_function: Optional[Callable[[ID], AsyncContextManager[bool]]] = None,
        validation_function: Optional[Callable[[PeerInfo], AsyncContextManager[bool]]] = None,
        enable_auto_refresh: bool = RANDOM_WALK_ENABLED,
        refresh_interval: float = REFRESH_INTERVAL,
        min_refresh_threshold: int = MIN_RT_REFRESH_THRESHOLD,
    ):
        """
        Initialize RT Refresh Manager.
        
        Args:
            host: The libp2p host instance
            routing_table: The routing table to manage
            local_peer_id: Local peer ID
            query_function: Function to perform DHT queries
            ping_function: Function to ping peers (optional)
            validation_function: Function to validate peers (optional)
            enable_auto_refresh: Whether to enable automatic refresh
            refresh_interval: Interval between refreshes in seconds
            min_refresh_threshold: Minimum RT size before triggering refresh
        """
        self.host = host
        self.routing_table = routing_table
        self.local_peer_id = local_peer_id
        self.query_function = query_function
        self.ping_function = ping_function
        self.validation_function = validation_function
        
        self.enable_auto_refresh = enable_auto_refresh
        self.refresh_interval = refresh_interval
        self.min_refresh_threshold = min_refresh_threshold
        
        # Initialize random walk module
        self.random_walk = RandomWalk(
            host=host,
            local_peer_id=local_peer_id,
            query_function=query_function,
            validation_function=validation_function,
            ping_function=ping_function
        )
        
        # Control variables
        self._running = False
        self._nursery: Optional[trio.Nursery] = None
        self._refresh_trigger_send: Optional[trio.MemorySendChannel] = None
        self._refresh_trigger_receive: Optional[trio.MemoryReceiveChannel] = None
        
        # Tracking
        self._last_refresh_time = 0.0
        self._refresh_done_callbacks: List[Callable[[], None]] = []
    
    async def start(self) -> None:
        """Start the RT Refresh Manager."""
        if self._running:
            logger.warning("RT Refresh Manager is already running")
            return
        
        self._running = True
        
        # Create trigger channels
        self._refresh_trigger_send, self._refresh_trigger_receive = trio.open_memory_channel(100)
        
        logger.info("Starting RT Refresh Manager")
        
        # Start the main loop
        async with trio.open_nursery() as nursery:
            self._nursery = nursery
            nursery.start_soon(self._main_loop)
    
    async def stop(self) -> None:
        """Stop the RT Refresh Manager."""
        if not self._running:
            return
        
        logger.info("Stopping RT Refresh Manager")
        self._running = False
        
        # Close trigger channels
        if self._refresh_trigger_send:
            await self._refresh_trigger_send.aclose()
        if self._refresh_trigger_receive:
            await self._refresh_trigger_receive.aclose()
    
    async def trigger_refresh(self, force: bool = False) -> None:
        """
        Trigger a manual refresh of the routing table.
        
        Args:
            force: Whether to force refresh regardless of timing
        """
        if not self._running or not self._refresh_trigger_send:
            logger.warning("Cannot trigger refresh: manager not running")
            return
        
        trigger = RefreshTrigger(force_refresh=force)
        try:
            await self._refresh_trigger_send.send(trigger)
            logger.debug(f"Refresh trigger sent (force={force})")
        except trio.BrokenResourceError:
            logger.warning("Cannot send refresh trigger: channel closed")
    
    async def _main_loop(self) -> None:
        """Main loop for the RT Refresh Manager."""
        logger.info("RT Refresh Manager main loop started")
        
        # Initial refresh if auto-refresh is enabled
        if self.enable_auto_refresh:
            await self._do_refresh(force=True)
        
        try:
            while self._running:
                async with trio.open_nursery() as nursery:
                    # Schedule periodic refresh if enabled
                    if self.enable_auto_refresh:
                        nursery.start_soon(self._periodic_refresh_task)
                    
                    # Handle manual refresh triggers
                    nursery.start_soon(self._handle_refresh_triggers)
                    
        except Exception as e:
            logger.error(f"RT Refresh Manager main loop error: {e}")
        finally:
            logger.info("RT Refresh Manager main loop stopped")
    
    async def _periodic_refresh_task(self) -> None:
        """Task for periodic refreshes."""
        while self._running:
            await trio.sleep(self.refresh_interval)
            if self._running:
                await self._do_refresh()
    
    async def _handle_refresh_triggers(self) -> None:
        """Handle manual refresh trigger requests."""
        if not self._refresh_trigger_receive:
            return
        
        while self._running:
            try:
                trigger = await self._refresh_trigger_receive.receive()
                await self._do_refresh(force=trigger.force_refresh)
            except trio.EndOfChannel:
                break
            except Exception as e:
                logger.error(f"Error handling refresh trigger: {e}")
    
    async def _do_refresh(self, force: bool = False) -> None:
        """
        Perform routing table refresh operation.
        
        Args:
            force: Whether to force refresh regardless of timing
        """
        try:
            current_time = time.time()
            
            # Check if refresh is needed
            if not force:
                if current_time - self._last_refresh_time < self.refresh_interval:
                    logger.debug("Skipping refresh: interval not elapsed")
                    return
                
                if self.routing_table.size() >= self.min_refresh_threshold:
                    logger.debug("Skipping refresh: routing table size above threshold")
                    return
            
            logger.info(f"Starting routing table refresh (force={force})")
            start_time = current_time
            
            # Ping and evict dead peers
            await self._ping_and_evict_peers()
            
            # Perform random walks to discover new peers
            discovered_peers = await self.random_walk.run_concurrent_random_walks()
            
            # Add discovered peers to routing table
            added_count = 0
            for peer_info in discovered_peers:
                if self.routing_table.add_peer(peer_info):
                    added_count += 1
            
            self._last_refresh_time = current_time
            
            duration = time.time() - start_time
            logger.info(
                f"Routing table refresh completed: "
                f"{added_count}/{len(discovered_peers)} peers added, "
                f"RT size: {self.routing_table.size()}, "
                f"duration: {duration:.2f}s"
            )
            
            # Notify refresh completion
            for callback in self._refresh_done_callbacks:
                try:
                    callback()
                except Exception as e:
                    logger.warning(f"Refresh callback error: {e}")
            
        except Exception as e:
            logger.error(f"Routing table refresh failed: {e}")
            raise RoutingTableRefreshError(f"Refresh operation failed: {e}") from e
    
    async def _ping_and_evict_peers(self) -> None:
        """
        Ping peers in the routing table and evict unresponsive ones.
        
        Similar to go-libp2p's pingAndEvictPeers function.
        """
        try:
            peers = self.routing_table.get_peer_infos()
            if not peers:
                return
            
            logger.debug(f"Pinging {len(peers)} peers for liveness check")
            
            async def check_peer_liveness(peer_info: PeerInfo):
                try:
                    # Skip if we have recent successful communication
                    # (This would need to be tracked in the routing table implementation)
                    
                    # Ping the peer
                    is_alive = False
                    if self.ping_function:
                        with trio.move_on_after(PEER_PING_TIMEOUT):
                            async with self.ping_function(peer_info.peer_id) as result:
                                is_alive = result
                    else:
                        # Fallback: try to connect
                        with trio.move_on_after(PEER_PING_TIMEOUT):
                            await self.host.connect(peer_info)
                            is_alive = True
                    
                    if not is_alive:
                        logger.debug(f"Evicting unresponsive peer: {peer_info.peer_id}")
                        self.routing_table.remove_peer(peer_info.peer_id)
                    
                except Exception as e:
                    logger.debug(f"Evicting peer {peer_info.peer_id} due to error: {e}")
                    self.routing_table.remove_peer(peer_info.peer_id)
            
            # Check peers concurrently
            async with trio.open_nursery() as nursery:
                for peer_info in peers:
                    nursery.start_soon(check_peer_liveness, peer_info)
            
            logger.debug("Peer liveness check completed")
            
        except Exception as e:
            logger.warning(f"Peer ping and evict operation failed: {e}")
    
    def add_refresh_done_callback(self, callback: Callable[[], None]) -> None:
        """Add a callback to be called when refresh completes."""
        self._refresh_done_callbacks.append(callback)
    
    def remove_refresh_done_callback(self, callback: Callable[[], None]) -> None:
        """Remove a refresh completion callback."""
        if callback in self._refresh_done_callbacks:
            self._refresh_done_callbacks.remove(callback)
