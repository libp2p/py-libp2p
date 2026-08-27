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

logger = logging.getLogger(__name__)


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

    async def perform_random_walk(
        self, target_key: bytes | None = None
    ) -> list[PeerInfo]:
        """
        Perform a single random walk operation.

        Args:
            target_key: Optional 32-byte target key to query for. If None,
                a random 32-byte key is generated.

        Returns:
            List of validated peers discovered during the walk

        """
        try:
            if target_key is None:
                random_peer_id = self.generate_random_peer_id()
                target_key = bytes.fromhex(random_peer_id)
                key_desc = f"{random_peer_id[:8]}..."
            else:
                key_desc = f"{target_key.hex()[:8]}..."

            logger.info(f"Starting random walk for target key: {key_desc}")

            # Perform FIND_NODE query
            discovered_peer_ids: list[ID] = []

            with trio.move_on_after(REFRESH_QUERY_TIMEOUT):
                discovered_peer_ids = await self.query_function(target_key) or []

            if not discovered_peer_ids:
                logger.debug(f"No peers discovered in random walk for {key_desc}")
                return []

            logger.info(
                f"Discovered {len(discovered_peer_ids)} peers in random walk "
                f"for {key_desc}"
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
        self,
        count: int = RANDOM_WALK_CONCURRENCY,
        current_routing_table_size: int = 0,
        target_keys: list[bytes] | None = None,
    ) -> list[PeerInfo]:
        """
        Run multiple random walks concurrently.

        Args:
            count: Number of concurrent random walks to perform
            current_routing_table_size: Current size of routing table (for optimization)
            target_keys: Optional list of targeted 32-byte keys (e.g. from K-buckets)

        Returns:
            Combined list of all validated peers discovered

        """
        all_validated_peers: list[PeerInfo] = []
        keys_to_query: list[bytes | None] = (
            [k for k in target_keys] if target_keys else [None for _ in range(count)]
        )

        logger.info(
            f"Starting {len(keys_to_query)} random walks (concurrency cap={count})"
        )

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

        sem = trio.Semaphore(count)

        async def single_walk(key: bytes | None) -> None:
            async with sem:
                try:
                    peers = await self.perform_random_walk(target_key=key)
                    all_validated_peers.extend(peers)
                except Exception as e:
                    logger.warning(f"Concurrent random walk failed: {e}")

        try:
            async with trio.open_nursery() as nursery:
                for key in keys_to_query:
                    nursery.start_soon(single_walk, key)
        except Exception as e:
            logger.debug(f"Random walk batch scope ended: {e}")

        # Remove duplicates based on peer ID
        unique_peers = {}
        for peer in all_validated_peers:
            unique_peers[peer.peer_id] = peer

        result = list(unique_peers.values())
        logger.info(
            f"Concurrent random walks completed: found {len(all_validated_peers)} total peers, "  # noqa: E501
            f"{len(result)} unique peers discovered"
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
        Check if a peer has compatible multiaddrs (TCP, QUIC, etc.).

        Args:
            peer_info: PeerInfo to check

        Returns:
            True if peer has compatible addresses

        """
        if not peer_info.addrs:
            return False

        for addr in peer_info.addrs:
            addr_str = str(addr)
            # Accept any routable IP multiaddr with TCP or QUIC
            if ("/ip4/" in addr_str or "/ip6/" in addr_str or "/dns" in addr_str) and (
                "/tcp/" in addr_str or "/quic" in addr_str or "/udp/" in addr_str
            ):
                return True

        return False
