"""
Kademlia DHT routing table implementation.
"""

from __future__ import annotations

from collections import (
    OrderedDict,
)
import hashlib
from ipaddress import (
    ip_address,
    ip_network,
)
import logging
import secrets
import time
from typing import TYPE_CHECKING

from multiaddr.exceptions import (
    ProtocolLookupError,
)
import trio

if TYPE_CHECKING:
    from .diagnostics import RoutingTableDiagnostics

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
    BUCKET_SIZE,
    MAX_PEERS_PER_SUBNET,
    MAXIMUM_BUCKETS,
    STALE_PEER_THRESHOLD,
    SUBNET_PREFIX_LEN_V4,
    SUBNET_PREFIX_LEN_V6,
)

logger = logging.getLogger(__name__)


def peer_id_to_key(peer_id: ID) -> bytes:
    """
    Convert a peer ID to a 256-bit key for routing table operations.
    This normalizes all peer IDs to exactly 256 bits by hashing them with SHA-256.

    :param peer_id: The peer ID to convert
    :return: 32-byte (256-bit) key for routing table operations
    """
    return hashlib.sha256(peer_id.to_bytes()).digest()


def key_to_int(key: bytes) -> int:
    """Convert a 256-bit key to an integer for range calculations."""
    return int.from_bytes(key, byteorder="big")


def gen_random_key_in_bucket(bucket: KBucket) -> bytes:
    """
    Generate a 32-byte key uniformly at random within the bucket's key range.
    Matches go-libp2p-kbucket targeted bucket refresh.
    """
    if bucket.max_range <= bucket.min_range + 1:
        val = bucket.min_range
    else:
        val = secrets.randbelow(bucket.max_range - bucket.min_range) + bucket.min_range
    return val.to_bytes(32, byteorder="big")


def _subnet_key(peer_info: PeerInfo) -> str | None:
    """
    Return a stable subnet key for a peer's first globally-routable IP address,
    used to enforce IP/subnet diversity in k-buckets (issue #1383).

    Returns ``None`` (peer exempt from the diversity check) when the peer has no
    globally-routable IP literal — this covers loopback, private (RFC1918/ULA),
    CGNAT (100.64.0.0/10), link-local, documentation ranges, DNS-named peers,
    and relayed (``p2p-circuit``) addresses. Only ``ip4``/``ip6`` literals on
    non-relayed multiaddrs are grouped; ``is_global`` is used as the routable
    predicate so behaviour is stable regardless of the exact private-range set.

    A relayed address carries the *relay's* IP, not the peer's, so it is skipped
    to avoid grouping distinct peers behind a shared relay.

    Divergence from go-libp2p (go-libp2p-kbucket/peerdiversity): go checks *every*
    address of the peer and rejects if any group is saturated. We group by the
    *first* globally-routable address only — simpler, and it avoids false
    rejections of legitimately multi-homed peers. A stricter all-addresses check
    is a reasonable follow-up once address ordering is well-defined.
    """
    for addr in peer_info.addrs:
        # Relayed addrs expose the relay's IP, not the peer's — never group them.
        if "p2p-circuit" in str(addr):
            continue
        for proto, prefix_len in (
            ("ip4", SUBNET_PREFIX_LEN_V4),
            ("ip6", SUBNET_PREFIX_LEN_V6),
        ):
            try:
                value = addr.value_for_protocol(proto)
                if value is None:
                    continue
                ip = ip_address(value)
            except (ProtocolLookupError, ValueError):
                continue
            if not ip.is_global:
                # loopback / private / CGNAT / link-local / doc range → exempt
                continue
            return str(ip_network(f"{ip}/{prefix_len}", strict=False))
    return None


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
        max_peers_per_subnet: int | None = None,
    ):
        """
        Initialize a new k-bucket.

        :param host: The host this bucket belongs to
        :param bucket_size: Maximum number of peers to store in the bucket
        :param min_range: Lower boundary of the bucket's key range (inclusive)
        :param max_range: Upper boundary of the bucket's key range (exclusive)
        :param max_peers_per_subnet: Per-bucket subnet-diversity cap (issue #1422).
            ``None`` resolves to ``MAX_PEERS_PER_SUBNET`` at call time so tests
            patching the module constant keep working; <= 0 disables the check.

        """
        self.bucket_size = bucket_size
        self.host = host
        self.min_range = min_range
        self.max_range = max_range
        # Keep None as a sentinel and resolve against MAX_PEERS_PER_SUBNET at
        # read time (see _subnet_limit) so tests that patch the module constant
        # after construction still take effect (issue #1422).
        self.max_peers_per_subnet = max_peers_per_subnet
        # Store PeerInfo objects along with last-seen timestamp
        self.peers: OrderedDict[ID, tuple[PeerInfo, float]] = OrderedDict()
        self._lock: trio.Lock = trio.Lock()

    def _subnet_limit(self) -> int:
        """
        Resolve the effective per-bucket subnet cap (issue #1422).

        ``None`` falls back to the module-level ``MAX_PEERS_PER_SUBNET`` (read at
        call time so tests can patch it); an explicit value overrides it.
        """
        if self.max_peers_per_subnet is None:
            return MAX_PEERS_PER_SUBNET
        return self.max_peers_per_subnet

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
        Add a peer to the bucket.

        Returns True if the peer was added or updated. Returns False if the
        bucket is full (and the oldest peer could not be replaced) or if the
        peer was rejected by IP/subnet diversity (issue #1383:
        ``MAX_PEERS_PER_SUBNET``).
        """
        async with self._lock:
            current_time = time.time()
            peer_id = peer_info.peer_id

            # If peer is already in the bucket, move it to the end (most recently seen)
            if peer_id in self.peers:
                self.refresh_peer_last_seen(peer_id)
                return True

            # Enforce IP/subnet diversity (issue #1383): refuse a new peer whose
            # globally-routable subnet already holds the per-bucket cap (issue
            # #1422). Exempt peers (subnet is None) are never grouped. Disabled
            # when the cap is <= 0.
            limit = self._subnet_limit()
            if limit > 0:
                subnet = _subnet_key(peer_info)
                if subnet is not None and self._peers_in_subnet(subnet) >= limit:
                    logger.debug(
                        "Subnet %s at capacity (%d), rejecting peer %s",
                        subnet,
                        limit,
                        peer_id,
                    )
                    return False

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

            # If the old peer is unresponsive, we can replace it with the new peer
            logger.debug(
                "Old peer %s is unresponsive, replacing with new peer %s",
                oldest_peer_id,
                peer_id,
            )
            if oldest_peer_id in self.peers:
                del self.peers[oldest_peer_id]

            self.peers[peer_id] = (peer_info, current_time)
            return True

    def _peers_in_subnet(self, subnet: str) -> int:
        """
        Count resident peers whose subnet key matches ``subnet`` (issue #1383).

        Recomputes ``_subnet_key`` for each resident peer; O(k) with k bounded
        by ``bucket_size`` (default 20), so the per-add cost is negligible.
        """
        return sum(1 for info, _ in self.peers.values() if _subnet_key(info) == subnet)

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

    async def _ping_peer(self, peer_id: ID) -> bool:
        """
        Ping a peer using the libp2p ping protocol to check
        if it's still alive and update last seen time.

        Per spec: "Implementations must not actively send PING requests"
        using the Kademlia protocol. We use the dedicated libp2p ping protocol.

        params: peer_id: The ID of the peer to ping

        Returns
        -------
        bool
            True if ping successful, False otherwise

        """
        from libp2p.host.ping import PingService

        try:
            ping_service = PingService(self.host)
            rtts = await ping_service.ping(peer_id, ping_amt=1)
            if rtts:
                logger.debug(
                    f"Successfully pinged peer {peer_id} "
                    f"(RTT: {rtts[0]}ms via libp2p ping)"
                )
                return True
            return False
        except Exception as e:
            logger.debug(f"Failed to ping peer {peer_id} via libp2p ping: {e}")
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
        key_int = key_to_int(key)
        return self.min_range <= key_int < self.max_range

    def peer_id_in_range(self, peer_id: ID) -> bool:
        """
        Check if a peer ID is in the range of this bucket.

        params: peer_id: The peer ID to check

        Returns
        -------
        bool
            True if the peer ID is in range, False otherwise

        """
        key = peer_id_to_key(peer_id)
        return self.key_in_range(key)

    def split(self) -> tuple[KBucket, KBucket]:
        """
        Split the bucket into two buckets.

        Returns
        -------
        tuple
            (lower_bucket, upper_bucket)

        """
        midpoint = (self.min_range + self.max_range) // 2
        lower_bucket = KBucket(
            self.host,
            self.bucket_size,
            self.min_range,
            midpoint,
            self.max_peers_per_subnet,
        )
        upper_bucket = KBucket(
            self.host,
            self.bucket_size,
            midpoint,
            self.max_range,
            self.max_peers_per_subnet,
        )

        # Redistribute peers
        for peer_id, (peer_info, timestamp) in self.peers.items():
            peer_key = peer_id_to_key(peer_id)
            peer_key_int = key_to_int(peer_key)
            if peer_key_int < midpoint:
                lower_bucket.peers[peer_id] = (peer_info, timestamp)
            else:
                upper_bucket.peers[peer_id] = (peer_info, timestamp)

        return lower_bucket, upper_bucket


class RoutingTable:
    """
    The Kademlia routing table maintains information on which peers to contact for any
    given peer ID in the network.
    """

    def __init__(
        self,
        local_id: ID,
        host: IHost,
        max_peers_per_subnet: int | None = None,
        max_peers_per_subnet_table: int = 0,
    ) -> None:
        """
        Initialize the routing table.

        :param local_id: The ID of the local node.
        :param host: The host this routing table belongs to.
        :param max_peers_per_subnet: Per-bucket subnet-diversity cap (issue
            #1422), propagated to every KBucket. ``None`` tracks the module
            default ``MAX_PEERS_PER_SUBNET``; <= 0 disables the per-bucket check.
        :param max_peers_per_subnet_table: Table-wide cap on peers sharing one
            subnet across all buckets (issue #1421). ``0`` (default) disables it.
            go-libp2p defaults its equivalent (``maxForTable``) to 3; we default
            to ``0`` for backward compatibility.

        """
        self.local_id = local_id
        self.host = host
        self.max_peers_per_subnet = max_peers_per_subnet
        self.max_peers_per_subnet_table = max_peers_per_subnet_table
        self.buckets = [
            KBucket(host, BUCKET_SIZE, max_peers_per_subnet=self.max_peers_per_subnet)
        ]

    async def add_peer(
        self, peer_obj: PeerInfo | ID, *, skip_server_mode_check: bool = False
    ) -> bool:
        """
        Add a peer to the routing table.

        Per spec: "Nodes add another node to their routing table if and only if
        that node operates in server mode." We check if the peer supports the
        KAD protocol via identify before adding, unless skip_server_mode_check
        is True (e.g., when adding from an incoming KAD stream).

        :param peer_obj: Either PeerInfo object or peer ID to add
        :param skip_server_mode_check: If True, skip the server-mode protocol check

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

            # Per spec: only add peers that operate in server mode.
            # A peer is in server mode if it supports the KAD protocol
            # (learned via identify protocol). Only check if identify has
            # populated protocol info for this peer.
            if not skip_server_mode_check:
                try:
                    from .common import PROTOCOL_ID

                    peer_protocols = self.host.get_peerstore().get_protocols(peer_id)
                    if peer_protocols is not None and len(peer_protocols) > 0:
                        # Identify has run — check if peer supports KAD
                        if str(PROTOCOL_ID) not in peer_protocols:
                            logger.debug(
                                "Peer %s does not support KAD protocol, "
                                "not adding to routing table (client mode)",
                                peer_id,
                            )
                            return False
                except Exception:
                    pass

            # Enforce the table-wide IP-group cap (issue #1421): reject a new
            # peer whose subnet already holds max_peers_per_subnet_table peers
            # across ALL buckets. Disabled by default (cap == 0). Exempt peers
            # (subnet is None) and updates to resident peers are never capped.
            if self.max_peers_per_subnet_table > 0 and not self.peer_in_table(peer_id):
                subnet = _subnet_key(peer_info)
                if (
                    subnet is not None
                    and self._table_peers_in_subnet(subnet)
                    >= self.max_peers_per_subnet_table
                ):
                    logger.debug(
                        "Table subnet %s at capacity (%d), rejecting peer %s",
                        subnet,
                        self.max_peers_per_subnet_table,
                        peer_id,
                    )
                    return False

            # Find the right bucket for this peer
            bucket = self.find_bucket(peer_id)

            # Keep splitting the bucket if it's full, we don't already have the peer,
            # and it contains our local ID. We might need to split multiple times
            # if all peers in the bucket happen to fall into the same half.
            while bucket.size() >= bucket.bucket_size and not bucket.has_peer(peer_id):
                if self._should_split_bucket(bucket):
                    logger.debug(f"Bucket full, attempting to split for peer {peer_id}")
                    if self._split_bucket(bucket):
                        # Re-find the bucket for this peer after the split
                        bucket = self.find_bucket(peer_id)
                    else:
                        break
                else:
                    break

            # Now try to add to the bucket. If it's still full (couldn't split),
            # this will ping the oldest peer and replace it if unresponsive.
            success = await bucket.add_peer(peer_info)
            if success:
                logger.debug("Successfully added peer %s to routing table", peer_id)
                return True

            subnet = _subnet_key(peer_info)
            bucket_limit = bucket._subnet_limit()
            if (
                bucket_limit > 0
                and subnet is not None
                and bucket._peers_in_subnet(subnet) >= bucket_limit
            ):
                logger.debug(
                    "Peer %s dropped: subnet %s at capacity (%d)",
                    peer_id,
                    subnet,
                    bucket_limit,
                )
            else:
                logger.debug(
                    "Bucket full and cannot split, peer %s dropped",
                    peer_id,
                )
            return False

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
        Find the bucket that would contain the given peer ID.

        :param peer_id: The peer ID to find a bucket for

        Returns
        -------
            KBucket: The bucket for this peer

        """
        for bucket in self.buckets:
            if bucket.peer_id_in_range(peer_id):
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

        # Hash the target key to map it into the DHT keyspace
        target_hash = hashlib.sha256(key).digest()

        # Sort by XOR distance to the key
        def distance_to_key(peer_id: ID) -> int:
            peer_key = peer_id_to_key(peer_id)
            return xor_distance(peer_key, target_hash)

        all_peers.sort(key=distance_to_key)

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

    def _table_peers_in_subnet(self, subnet: str) -> int:
        """
        Count resident peers whose subnet key matches ``subnet`` across all
        buckets (issue #1421, table-wide IP-group cap).
        """
        return sum(bucket._peers_in_subnet(subnet) for bucket in self.buckets)

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

    def get_peer_infos(self) -> list[PeerInfo]:
        """
        Get all PeerInfo objects in the routing table.

        Returns
        -------
            List[PeerInfo]: List of all PeerInfo objects

        """
        peer_infos = []
        for bucket in self.buckets:
            peer_infos.extend(bucket.peer_infos())
        return peer_infos

    def cleanup_routing_table(self) -> None:
        """
        Cleanup the routing table by removing all data.
        This is useful for resetting the routing table during tests or reinitialization.
        """
        self.buckets = [
            KBucket(
                self.host,
                BUCKET_SIZE,
                max_peers_per_subnet=self.max_peers_per_subnet,
            )
        ]
        logger.info("Routing table cleaned up, all data removed.")

    def get_target_keys_for_refresh(self) -> list[bytes]:
        """
        Return targeted 32-byte keys for each active bucket in the routing table.
        Matches go-libp2p rtrefresh strategy.
        """
        return [gen_random_key_in_bucket(bucket) for bucket in self.buckets]

    def get_diagnostics(self) -> RoutingTableDiagnostics:
        """
        Return a :class:`~libp2p.kad_dht.diagnostics.RoutingTableDiagnostics`
        analyser bound to this routing table.

        Example::

            report = dht.routing_table.get_diagnostics().analyse()
            print(report.summary())
        """
        from .diagnostics import RoutingTableDiagnostics

        return RoutingTableDiagnostics(self)

    def _should_split_bucket(self, bucket: KBucket) -> bool:
        """
        Check if a bucket should be split according to Kademlia rules.

        Per spec: "must try to maintain k peers with shared key prefix of
        length L, for every L in [0..255]". We split any full bucket up
        to the maximum of 256 buckets.

        :param bucket: The bucket to check
        :return: True if the bucket should be split
        """
        # Only full buckets should ever split. A non-full bucket can now return
        # False from add_peer for reasons other than fullness (e.g. a subnet
        # diversity rejection, issue #1383), which must not trigger a split.
        if len(bucket.peers) < bucket.bucket_size:
            return False

        # Check if we've exceeded maximum buckets
        if len(self.buckets) >= MAXIMUM_BUCKETS:
            logger.debug("Maximum number of buckets reached, cannot split")
            return False

        return True

    def _split_bucket(self, bucket: KBucket) -> bool:
        """
        Split a bucket into two buckets.

        :param bucket: The bucket to split
        :return: True if the bucket was successfully split

        """
        try:
            # Find the bucket index
            bucket_index = self.buckets.index(bucket)
            logger.debug(f"Splitting bucket at index {bucket_index}")

            # Split the bucket
            lower_bucket, upper_bucket = bucket.split()

            # Replace the original bucket with the two new buckets
            self.buckets[bucket_index] = lower_bucket
            self.buckets.insert(bucket_index + 1, upper_bucket)

            logger.debug(
                f"Bucket split successful. New bucket count: {len(self.buckets)}"
            )
            logger.debug(
                f"Lower bucket range: "
                f"{lower_bucket.min_range} - {lower_bucket.max_range}, "
                f"peers: {lower_bucket.size()}"
            )
            logger.debug(
                f"Upper bucket range: "
                f"{upper_bucket.min_range} - {upper_bucket.max_range}, "
                f"peers: {upper_bucket.size()}"
            )

            return True

        except Exception as e:
            logger.error(f"Error splitting bucket: {e}")
            return False

    async def _periodic_peer_refresh(self) -> None:
        """
        Periodically refresh stale peers across all buckets.

        Single table-level background task that runs every 5 minutes.
        """
        try:
            while True:
                await trio.sleep(300.0)  # Check every 5 minutes

                # Collect stale peers across all buckets
                stale_peers: list[ID] = []
                for bucket in self.buckets:
                    stale = bucket.get_stale_peers(
                        stale_threshold_seconds=STALE_PEER_THRESHOLD
                    )
                    stale_peers.extend(stale)

                if not stale_peers:
                    continue

                # Rate-limit pings: at most 5 peers per 5-minute cycle
                logger.debug(
                    f"Found {len(stale_peers)} stale peers in routing table; "
                    f"refreshing up to 5"
                )
                for peer_id in stale_peers[:5]:
                    try:
                        # Find which bucket contains this peer
                        target_bucket = self.find_bucket(peer_id)
                        if target_bucket is None:
                            continue

                        response = await target_bucket._ping_peer(peer_id)
                        if response:
                            target_bucket.refresh_peer_last_seen(peer_id)
                            logger.debug(f"Refreshed stale peer {peer_id}")
                        else:
                            target_bucket.remove_peer(peer_id)
                            logger.info(f"Removed unresponsive stale peer {peer_id}")
                    except Exception as e:
                        logger.debug(f"Error checking stale peer {peer_id}: {e}")
                    # 1s stagger between individual stale pings
                    await trio.sleep(1.0)
        except trio.Cancelled:
            logger.debug("Routing table peer refresh task cancelled")
        except Exception as e:
            logger.error(
                f"Error in routing table peer refresh task: {e}", exc_info=True
            )

    def start_periodic_refresh(self, nursery: trio.Nursery) -> None:
        """Start single periodic stale peer refresh task for the routing table."""
        nursery.start_soon(self._periodic_peer_refresh)
