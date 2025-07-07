"""
Kademlia DHT routing table implementation.
"""

from collections import (
    OrderedDict,
)
import logging
import time

import trio

from libp2p.abc import (
    IHost,
)
from libp2p.kad_dht.utils import (
    xor_distance,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.peer.peerinfo import (
    PeerInfo,
)

from .common import (
    PROTOCOL_ID,
)
from .pb.kademlia_pb2 import (
    Message,
)

# logger = logging.getLogger("libp2p.kademlia.routing_table")
logger = logging.getLogger("kademlia-example.routing_table")

# Default parameters
BUCKET_SIZE = 20  # k in the Kademlia paper
MAXIMUM_BUCKETS = 256  # Maximum number of buckets (for 256-bit keys)
PEER_REFRESH_INTERVAL = 60  # Interval to refresh peers in seconds
STALE_PEER_THRESHOLD = 3600  # Time in seconds after which a peer is considered stale


class KBucket:
    """
    A k-bucket implementation for the Kademlia DHT.

    Each k-bucket stores up to k (BUCKET_SIZE) peers, sorted by least-recently seen.
    """

    def __init__(
        self,
        host: IHost,
        bucket_size: int = BUCKET_SIZE,
        min_range: int = 0,
        max_range: int = 2**256,
    ):
        """
        Initialize a new k-bucket.

        :param host: The host this bucket belongs to
        :param bucket_size: Maximum number of peers to store in the bucket
        :param min_range: Lower boundary of the bucket's key range (inclusive)
        :param max_range: Upper boundary of the bucket's key range (exclusive)

        """
        self.bucket_size = bucket_size
        self.host = host
        self.min_range = min_range
        self.max_range = max_range
        # Store PeerInfo objects along with last-seen timestamp
        self.peers: OrderedDict[ID, tuple[PeerInfo, float]] = OrderedDict()

    def peer_ids(self) -> list[ID]:
        """Get all peer IDs in the bucket."""
        return list(self.peers.keys())

    def peer_infos(self) -> list[PeerInfo]:
        """Get all PeerInfo objects in the bucket."""
        return [info for info, _ in self.peers.values()]

    def get_oldest_peer(self) -> ID | None:
        """Get the least-recently seen peer."""
        if not self.peers:
            return None
        return next(iter(self.peers.keys()))

    async def add_peer(self, peer_info: PeerInfo) -> bool:
        """
        Add a peer to the bucket. Returns True if the peer was added or updated,
        False if the bucket is full.
        """
        current_time = time.time()
        peer_id = peer_info.peer_id

        # If peer is already in the bucket, move it to the end (most recently seen)
        if peer_id in self.peers:
            self.refresh_peer_last_seen(peer_id)
            return True

        # If bucket has space, add the peer
        if len(self.peers) < self.bucket_size:
            self.peers[peer_id] = (peer_info, current_time)
            return True

        # If bucket is full, we need to replace the least-recently seen peer
        # Get the least-recently seen peer
        oldest_peer_id = self.get_oldest_peer()
        if oldest_peer_id is None:
            logger.warning("No oldest peer found when bucket is full")
            return False

        # Check if the old peer is responsive to ping request
        try:
            # Try to ping the oldest peer, not the new peer
            response = await self._ping_peer(oldest_peer_id)
            if response:
                # If the old peer is still alive, we will not add the new peer
                logger.debug(
                    "Old peer %s is still alive, cannot add new peer %s",
                    oldest_peer_id,
                    peer_id,
                )
                return False
        except Exception as e:
            # If the old peer is unresponsive, we can replace it with the new peer
            logger.debug(
                "Old peer %s is unresponsive, replacing with new peer %s: %s",
                oldest_peer_id,
                peer_id,
                str(e),
            )
            self.peers.popitem(last=False)  # Remove oldest peer
            self.peers[peer_id] = (peer_info, current_time)
            return True

        # If we got here, the oldest peer responded but we couldn't add the new peer
        return False

    def remove_peer(self, peer_id: ID) -> bool:
        """
        Remove a peer from the bucket.
        Returns True if the peer was in the bucket, False otherwise.
        """
        if peer_id in self.peers:
            del self.peers[peer_id]
            return True
        return False

    def has_peer(self, peer_id: ID) -> bool:
        """Check if the peer is in the bucket."""
        return peer_id in self.peers

    def get_peer_info(self, peer_id: ID) -> PeerInfo | None:
        """Get the PeerInfo for a given peer ID if it exists in the bucket."""
        if peer_id in self.peers:
            return self.peers[peer_id][0]
        return None

    def size(self) -> int:
        """Get the number of peers in the bucket."""
        return len(self.peers)

    def get_stale_peers(self, stale_threshold_seconds: int = 3600) -> list[ID]:
        """
        Get peers that haven't been pinged recently.

        params: stale_threshold_seconds: Time in seconds
        params: after which a peer is considered stale

        Returns
        -------
        list[ID]
            List of peer IDs that need to be refreshed

        """
        current_time = time.time()
        stale_peers = []

        for peer_id, (_, last_seen) in self.peers.items():
            if current_time - last_seen > stale_threshold_seconds:
                stale_peers.append(peer_id)

        return stale_peers

    async def _periodic_peer_refresh(self) -> None:
        """Background task to periodically refresh peers"""
        try:
            while True:
                await trio.sleep(PEER_REFRESH_INTERVAL)  # Check every minute

                # Find stale peers (not pinged in last hour)
                stale_peers = self.get_stale_peers(
                    stale_threshold_seconds=STALE_PEER_THRESHOLD
                )
                if stale_peers:
                    logger.debug(f"Found {len(stale_peers)} stale peers to refresh")

                    for peer_id in stale_peers:
                        try:
                            # Try to ping the peer
                            logger.debug("Pinging stale peer %s", peer_id)
                            responce = await self._ping_peer(peer_id)
                            if responce:
                                # Update the last seen time
                                self.refresh_peer_last_seen(peer_id)
                                logger.debug(f"Refreshed peer {peer_id}")
                            else:
                                # If ping fails, remove the peer
                                logger.debug(f"Failed to ping peer {peer_id}")
                                self.remove_peer(peer_id)
                                logger.info(f"Removed unresponsive peer {peer_id}")

                            logger.debug(f"Successfully refreshed peer {peer_id}")
                        except Exception as e:
                            # If ping fails, remove the peer
                            logger.debug(
                                "Failed to ping peer %s: %s",
                                peer_id,
                                e,
                            )
                            self.remove_peer(peer_id)
                            logger.info(f"Removed unresponsive peer {peer_id}")
        except trio.Cancelled:
            logger.debug("Peer refresh task cancelled")
        except Exception as e:
            logger.error(f"Error in peer refresh task: {e}", exc_info=True)

    async def _ping_peer(self, peer_id: ID) -> bool:
        """
        Ping a peer using protobuf message to check
        if it's still alive and update last seen time.

        params: peer_id: The ID of the peer to ping

        Returns
        -------
        bool
            True if ping successful, False otherwise

        """
        result = False
        # Get peer info directly from the bucket
        peer_info = self.get_peer_info(peer_id)
        if not peer_info:
            raise ValueError(f"Peer {peer_id} not in bucket")

        try:
            # Open a stream to the peer with the DHT protocol
            stream = await self.host.new_stream(peer_id, [PROTOCOL_ID])

            try:
                # Create ping protobuf message
                ping_msg = Message()
                ping_msg.type = Message.PING  # Use correct enum

                # Serialize and send with length prefix (4 bytes big-endian)
                msg_bytes = ping_msg.SerializeToString()
                logger.debug(
                    f"Sending PING message to {peer_id}, size: {len(msg_bytes)} bytes"
                )
                await stream.write(len(msg_bytes).to_bytes(4, byteorder="big"))
                await stream.write(msg_bytes)

                # Wait for response with timeout
                with trio.move_on_after(2):  # 2 second timeout
                    # Read response length (4 bytes)
                    length_bytes = await stream.read(4)
                    if not length_bytes or len(length_bytes) < 4:
                        logger.warning(f"Peer {peer_id} disconnected during ping")
                        return False

                    msg_len = int.from_bytes(length_bytes, byteorder="big")
                    if (
                        msg_len <= 0 or msg_len > 1024 * 1024
                    ):  # Sanity check on message size
                        logger.warning(
                            f"Invalid message length from {peer_id}: {msg_len}"
                        )
                        return False

                    logger.debug(
                        f"Receiving response from {peer_id}, size: {msg_len} bytes"
                    )

                    # Read full message
                    response_bytes = await stream.read(msg_len)
                    if not response_bytes:
                        logger.warning(f"Failed to read response from {peer_id}")
                        return False

                    # Parse protobuf response
                    response = Message()
                    try:
                        response.ParseFromString(response_bytes)
                    except Exception as e:
                        logger.warning(
                            f"Failed to parse protobuf response from {peer_id}: {e}"
                        )
                        return False

                    if response.type == Message.PING:
                        # Update the last seen timestamp for this peer
                        logger.debug(f"Successfully pinged peer {peer_id}")
                        result = True
                        return result

                    else:
                        logger.warning(
                            f"Unexpected response type from {peer_id}: {response.type}"
                        )
                        return False

                # If we get here, the ping timed out
                logger.warning(f"Ping to peer {peer_id} timed out")
                return False

            finally:
                await stream.close()
                return result

        except Exception as e:
            logger.error(f"Error pinging peer {peer_id}: {str(e)}")
            return False

    def refresh_peer_last_seen(self, peer_id: ID) -> bool:
        """
        Update the last-seen timestamp for a peer in the bucket.

        params: peer_id: The ID of the peer to refresh

        Returns
        -------
        bool
            True if the peer was found and refreshed, False otherwise

        """
        if peer_id in self.peers:
            # Get current peer info and update the timestamp
            peer_info, _ = self.peers[peer_id]
            current_time = time.time()
            self.peers[peer_id] = (peer_info, current_time)
            # Move to end of ordered dict to mark as most recently seen
            self.peers.move_to_end(peer_id)
            return True

        return False

    def key_in_range(self, key: bytes) -> bool:
        """
        Check if a key is in the range of this bucket.

        params: key: The key to check (bytes)

        Returns
        -------
        bool
            True if the key is in range, False otherwise

        """
        key_int = int.from_bytes(key, byteorder="big")
        return self.min_range <= key_int < self.max_range

    def split(self) -> tuple["KBucket", "KBucket"]:
        """
        Split the bucket into two buckets.

        Returns
        -------
        tuple
            (lower_bucket, upper_bucket)

        """
        midpoint = (self.min_range + self.max_range) // 2
        lower_bucket = KBucket(self.host, self.bucket_size, self.min_range, midpoint)
        upper_bucket = KBucket(self.host, self.bucket_size, midpoint, self.max_range)

        # Redistribute peers
        for peer_id, (peer_info, timestamp) in self.peers.items():
            peer_key = int.from_bytes(peer_id.to_bytes(), byteorder="big")
            if peer_key < midpoint:
                lower_bucket.peers[peer_id] = (peer_info, timestamp)
            else:
                upper_bucket.peers[peer_id] = (peer_info, timestamp)

        return lower_bucket, upper_bucket


class RoutingTable:
    """
    The Kademlia routing table maintains information on which peers to contact for any
    given peer ID in the network.
    """

    def __init__(self, local_id: ID, host: IHost) -> None:
        """
        Initialize the routing table.

        :param local_id: The ID of the local node.
        :param host: The host this routing table belongs to.

        """
        self.local_id = local_id
        self.host = host
        self.buckets = [KBucket(host, BUCKET_SIZE)]

    async def add_peer(self, peer_obj: PeerInfo | ID) -> bool:
        """
        Add a peer to the routing table.

        :param peer_obj: Either PeerInfo object or peer ID to add

        Returns
        -------
            bool: True if the peer was added or updated, False otherwise

        """
        peer_id = None
        peer_info = None

        try:
            # Handle different types of input
            if isinstance(peer_obj, PeerInfo):
                # Already have PeerInfo object
                peer_info = peer_obj
                peer_id = peer_obj.peer_id
            else:
                # Assume it's a peer ID
                peer_id = peer_obj
                # Try to get addresses from the peerstore if available
                try:
                    addrs = self.host.get_peerstore().addrs(peer_id)
                    if addrs:
                        # Create PeerInfo object
                        peer_info = PeerInfo(peer_id, addrs)
                    else:
                        logger.debug(
                            "No addresses found for peer %s in peerstore, skipping",
                            peer_id,
                        )
                        return False
                except Exception as peerstore_error:
                    # Handle case where peer is not in peerstore yet
                    logger.debug(
                        "Peer %s not found in peerstore: %s, skipping",
                        peer_id,
                        str(peerstore_error),
                    )
                    return False

            # Don't add ourselves
            if peer_id == self.local_id:
                return False

            # Find the right bucket for this peer
            bucket = self.find_bucket(peer_id)

            # Try to add to the bucket
            success = await bucket.add_peer(peer_info)
            if success:
                logger.debug(f"Successfully added peer {peer_id} to routing table")
            return success

        except Exception as e:
            logger.debug(f"Error adding peer {peer_obj} to routing table: {e}")
            return False

    def remove_peer(self, peer_id: ID) -> bool:
        """
        Remove a peer from the routing table.

        :param peer_id: The ID of the peer to remove

        Returns
        -------
            bool: True if the peer was removed, False otherwise

        """
        bucket = self.find_bucket(peer_id)
        return bucket.remove_peer(peer_id)

    def find_bucket(self, peer_id: ID) -> KBucket:
        """
        Find the bucket that would contain the given peer ID or PeerInfo.

        :param peer_obj: Either a peer ID or a PeerInfo object

        Returns
        -------
            KBucket: The bucket for this peer

        """
        for bucket in self.buckets:
            if bucket.key_in_range(peer_id.to_bytes()):
                return bucket

        return self.buckets[0]

    def find_local_closest_peers(self, key: bytes, count: int = 20) -> list[ID]:
        """
        Find the closest peers to a given key.

        :param key: The key to find closest peers to (bytes)
        :param count: Maximum number of peers to return

        Returns
        -------
            List[ID]: List of peer IDs closest to the key

        """
        # Get all peers from all buckets
        all_peers = []
        for bucket in self.buckets:
            all_peers.extend(bucket.peer_ids())

        # Sort by XOR distance to the key
        all_peers.sort(key=lambda p: xor_distance(p.to_bytes(), key))

        return all_peers[:count]

    def get_peer_ids(self) -> list[ID]:
        """
        Get all peer IDs in the routing table.

        Returns
        -------
        :param List[ID]: List of all peer IDs

        """
        peers = []
        for bucket in self.buckets:
            peers.extend(bucket.peer_ids())
        return peers

    def get_peer_info(self, peer_id: ID) -> PeerInfo | None:
        """
        Get the peer info for a specific peer.

        :param peer_id: The ID of the peer to get info for

        Returns
        -------
            PeerInfo: The peer info, or None if not found

        """
        bucket = self.find_bucket(peer_id)
        return bucket.get_peer_info(peer_id)

    def peer_in_table(self, peer_id: ID) -> bool:
        """
        Check if a peer is in the routing table.

        :param peer_id: The ID of the peer to check

        Returns
        -------
            bool: True if the peer is in the routing table, False otherwise

        """
        bucket = self.find_bucket(peer_id)
        return bucket.has_peer(peer_id)

    def size(self) -> int:
        """
        Get the number of peers in the routing table.

        Returns
        -------
            int: Number of peers

        """
        count = 0
        for bucket in self.buckets:
            count += bucket.size()
        return count

    def get_stale_peers(self, stale_threshold_seconds: int = 3600) -> list[ID]:
        """
        Get all stale peers from all buckets

        params: stale_threshold_seconds:
            Time in seconds after which a peer is considered stale

        Returns
        -------
        list[ID]
            List of stale peer IDs

        """
        stale_peers = []
        for bucket in self.buckets:
            stale_peers.extend(bucket.get_stale_peers(stale_threshold_seconds))
        return stale_peers

    def cleanup_routing_table(self) -> None:
        """
        Cleanup the routing table by removing all data.
        This is useful for resetting the routing table during tests or reinitialization.
        """
        self.buckets = [KBucket(self.host, BUCKET_SIZE)]
        logger.info("Routing table cleaned up, all data removed.")
