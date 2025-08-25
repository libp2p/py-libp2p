from collections.abc import Awaitable, Callable
import logging
import secrets

import trio

from libp2p.abc import IHost
from libp2p.discovery.random_walk.config import (
    RANDOM_WALK_CONCURRENCY,
    RANDOM_WALK_RT_THRESHOLD,
    REFRESH_QUERY_TIMEOUT,
)
from libp2p.discovery.random_walk.exceptions import RandomWalkError
from libp2p.peer.id import ID
from libp2p.peer.peerinfo import PeerInfo

logger = logging.getLogger("libp2p.discovery.random_walk")


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
        query_function: Callable[[bytes], Awaitable[list[ID]]],
    ):
        """
        Initialize Random Walk module.

        Args:
            host: The libp2p host instance
            local_peer_id: Local peer ID
            query_function: Function to query for closest peers given target key bytes

        """
        self.host = host
        self.local_peer_id = local_peer_id
        self.query_function = query_function

    def generate_random_peer_id(self) -> str:
        """
        Generate a completely random peer ID
         for random walk queries.

        Returns:
            Random peer ID as string

        """
        # Generate 32 random bytes (256 bits) - same as go-libp2p
        random_bytes = secrets.token_bytes(32)
        # Convert to hex string for query
        return random_bytes.hex()

    async def perform_random_walk(self) -> list[PeerInfo]:
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
            discovered_peer_ids: list[ID] = []

            with trio.move_on_after(REFRESH_QUERY_TIMEOUT):
                # Call the query function with target key bytes
                target_key = bytes.fromhex(random_peer_id)
                discovered_peer_ids = await self.query_function(target_key) or []

            if not discovered_peer_ids:
                logger.debug(f"No peers discovered in random walk for {random_peer_id}")
                return []

            logger.info(
                f"Discovered {len(discovered_peer_ids)} peers in random walk "
                f"for {random_peer_id[:8]}..."  # Show only first 8 chars for brevity
            )

            # Convert peer IDs to PeerInfo objects and validate
            validated_peers: list[PeerInfo] = []

            for peer_id in discovered_peer_ids:
                try:
                    # Get addresses from peerstore
                    addrs = self.host.get_peerstore().addrs(peer_id)
                    if addrs:
                        peer_info = PeerInfo(peer_id, addrs)
                        validated_peers.append(peer_info)
                except Exception as e:
                    logger.debug(f"Failed to create PeerInfo for {peer_id}: {e}")
                    continue

            return validated_peers

        except Exception as e:
            logger.error(f"Random walk failed: {e}")
            raise RandomWalkError(f"Random walk operation failed: {e}") from e

    async def run_concurrent_random_walks(
        self, count: int = RANDOM_WALK_CONCURRENCY, current_routing_table_size: int = 0
    ) -> list[PeerInfo]:
        """
        Run multiple random walks concurrently.

        Args:
            count: Number of concurrent random walks to perform
            current_routing_table_size: Current size of routing table (for optimization)

        Returns:
            Combined list of all validated peers discovered

        """
        all_validated_peers: list[PeerInfo] = []
        logger.info(f"Starting {count} concurrent random walks")

        # First, try to add peers from peerstore if routing table is small
        if current_routing_table_size < RANDOM_WALK_RT_THRESHOLD:
            try:
                peerstore_peers = self._get_peerstore_peers()
                if peerstore_peers:
                    logger.debug(
                        f"RT size ({current_routing_table_size}) below threshold, "
                        f"adding {len(peerstore_peers)} peerstore peers"
                    )
                all_validated_peers.extend(peerstore_peers)
            except Exception as e:
                logger.warning(f"Error processing peerstore peers: {e}")

        async def single_walk() -> None:
            try:
                peers = await self.perform_random_walk()
                all_validated_peers.extend(peers)
            except Exception as e:
                logger.warning(f"Concurrent random walk failed: {e}")
            return

        # Run concurrent random walks
        async with trio.open_nursery() as nursery:
            for _ in range(count):
                nursery.start_soon(single_walk)

        # Remove duplicates based on peer ID
        unique_peers = {}
        for peer in all_validated_peers:
            unique_peers[peer.peer_id] = peer

        result = list(unique_peers.values())
        logger.info(
            f"Concurrent random walks completed: {len(result)} unique peers discovered"
        )
        return result

    def _get_peerstore_peers(self) -> list[PeerInfo]:
        """
        Get peer info objects from the host's peerstore.

        Returns:
            List of PeerInfo objects from peerstore

        """
        try:
            peerstore = self.host.get_peerstore()
            peer_ids = peerstore.peers_with_addrs()

            peer_infos = []
            for peer_id in peer_ids:
                try:
                    # Skip local peer
                    if peer_id == self.local_peer_id:
                        continue

                    peer_info = peerstore.peer_info(peer_id)
                    if peer_info and peer_info.addrs:
                        # Filter for compatible addresses (TCP + IPv4)
                        if self._has_compatible_addresses(peer_info):
                            peer_infos.append(peer_info)
                except Exception as e:
                    logger.debug(f"Error getting peer info for {peer_id}: {e}")

            return peer_infos

        except Exception as e:
            logger.warning(f"Error accessing peerstore: {e}")
            return []

    def _has_compatible_addresses(self, peer_info: PeerInfo) -> bool:
        """
        Check if a peer has TCP+IPv4 compatible addresses.

        Args:
            peer_info: PeerInfo to check

        Returns:
            True if peer has compatible addresses

        """
        if not peer_info.addrs:
            return False

        for addr in peer_info.addrs:
            addr_str = str(addr)
            # Check for TCP and IPv4 compatibility, avoid QUIC
            if "/tcp/" in addr_str and "/ip4/" in addr_str and "/quic" not in addr_str:
                return True

        return False
