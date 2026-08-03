"""
Peer routing implementation for Kademlia DHT.

This module implements the peer routing interface using Kademlia's algorithm
to efficiently locate peers in a distributed network.
"""

import logging
import os

import trio
import varint

from libp2p.abc import (
    IHost,
    IPeerRouting,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.peer.peerinfo import (
    PeerInfo,
)
from libp2p.peer.peerstore import env_to_send_in_RPC

from .common import (
    ALPHA,
    BETA,
    BUCKET_SIZE,
    PROTOCOL_ID,
    QUERY_TIMEOUT,
)
from .pb.kademlia_pb2 import (
    Message,
)
from .routing_table import (
    RoutingTable,
)
from .utils import (
    maybe_consume_signed_record,
    sort_peer_ids_by_distance,
)

logger = logging.getLogger(__name__)

MAX_PEER_LOOKUP_ROUNDS = 20  # Maximum number of rounds in peer lookup
MIN_PEERS_THRESHOLD = 5  # Minimum peers threshold for fallback to connected peers


class PeerRouting(IPeerRouting):
    """
    Implementation of peer routing using the Kademlia algorithm.

    This class provides methods to find peers in the DHT network
    and helps maintain the routing table.
    """

    def __init__(self, host: IHost, routing_table: RoutingTable):
        """
        Initialize the peer routing service.

        :param host: The libp2p host
        :param routing_table: The Kademlia routing table

        """
        self.host = host
        self.routing_table = routing_table

    async def find_peer(self, peer_id: ID) -> PeerInfo | None:
        """
        Find a peer with the given ID.

        :param peer_id: The ID of the peer to find

        Returns
        -------
        Optional[PeerInfo]
            The peer information if found, None otherwise

        """
        # Check if this is actually our peer ID
        if peer_id == self.host.get_id():
            try:
                # Return our own peer info
                return PeerInfo(peer_id, self.host.get_addrs())
            except Exception:
                logger.exception("Error getting our own peer info")
                return None

        # First check if the peer is in our routing table
        peer_info = self.routing_table.get_peer_info(peer_id)
        if peer_info:
            logger.debug(f"Found peer {peer_id} in routing table")
            return peer_info

        # Then check if the peer is in our peerstore
        try:
            addrs = self.host.get_peerstore().addrs(peer_id)
            if addrs:
                logger.debug(f"Found peer {peer_id} in peerstore")
                return PeerInfo(peer_id, addrs)
        except Exception:
            pass

        # If not found locally, search the network
        try:
            closest_peers = await self.find_closest_peers_network(peer_id.to_bytes())
            logger.info(f"Closest peers found: {closest_peers}")

            # Check if we found the peer we're looking for
            for found_peer in closest_peers:
                if found_peer == peer_id:
                    try:
                        addrs = self.host.get_peerstore().addrs(found_peer)
                        if addrs:
                            return PeerInfo(found_peer, addrs)
                    except Exception:
                        pass

            # Re-check the peerstore after the network lookup. During the
            # iterative lookup, the target peer's signed record may have
            # been discovered and added to the peerstore (via
            # maybe_consume_signed_record) even if it wasn't in the top
            # 'count' closest peers. go-libp2p does the same.
            try:
                addrs = self.host.get_peerstore().addrs(peer_id)
                if addrs:
                    logger.debug(
                        f"Found peer {peer_id} in peerstore after network lookup"
                    )
                    return PeerInfo(peer_id, addrs)
            except Exception:
                pass

        except Exception as e:
            logger.error(f"Error searching for peer {peer_id}: {e}")

        # Not found
        logger.info(f"Peer {peer_id} not found")
        return None

    async def _query_single_peer_for_closest(
        self, peer: ID, target_key: bytes, new_peers: list[ID]
    ) -> None:
        """
        Query a single peer for closest peers and append results to the shared list.

        params: peer : ID
            The peer to query
        params: target_key : bytes
            The target key to find closest peers for
        params: new_peers : list[ID]
            Shared list to append results to

        """
        try:
            result = await self._query_peer_for_closest(peer, target_key)
            # Add deduplication to prevent duplicate peers
            for peer_id in result:
                if peer_id not in new_peers:
                    new_peers.append(peer_id)
            logger.debug(
                "Queried peer %s for closest peers, got %d results (%d unique)",
                peer,
                len(result),
                len([p for p in result if p not in new_peers[: -len(result)]]),
            )
        except Exception as e:
            logger.debug(f"Query to peer {peer} failed: {e}")

    async def find_closest_peers_network(
        self, target_key: bytes, count: int = 20
    ) -> list[ID]:
        """
        Find the closest peers to a target key in the entire network.

        Performs an iterative lookup by querying peers for their closest peers.
        If the routing table has fewer peers than MIN_PEERS_THRESHOLD, it falls
        back to using connected peers first, then peers from the peerstore if
        needed, to gather up to 'count' initial query targets.

        Returns
        -------
        list[ID]
            Closest peer IDs

        """
        # Start with closest peers from our routing table
        closest_peers = self.routing_table.find_local_closest_peers(target_key, count)
        logger.debug("Local closest peers: %d found", len(closest_peers))

        # Fallback to connected peers and peerstore if routing table has
        # insufficient peers
        if len(closest_peers) < MIN_PEERS_THRESHOLD:
            # First, try connected peers
            connected_peers = self.host.get_connected_peers()
            if connected_peers:
                logger.debug(
                    "Routing table has insufficient peers (%d < %d), "
                    "adding %d connected peers",
                    len(closest_peers),
                    MIN_PEERS_THRESHOLD,
                    len(connected_peers),
                )
                closest_peers.extend(connected_peers)

            # If still not enough, get peers from peerstore
            if len(closest_peers) < count:
                try:
                    peerstore_peers = self.host.get_peerstore().peer_ids()
                    # Filter out our own ID and already included peers
                    local_id = self.host.get_id()
                    existing_peers = set(closest_peers)
                    new_peerstore_peers = [
                        p
                        for p in peerstore_peers
                        if p != local_id and p not in existing_peers
                    ]
                    if new_peerstore_peers:
                        logger.debug(
                            "Adding %d peers from peerstore", len(new_peerstore_peers)
                        )
                        closest_peers.extend(new_peerstore_peers)
                except Exception as e:
                    logger.debug(f"Failed to get peers from peerstore: {e}")

            # Deduplicate and sort by distance, keeping closest peers
            closest_peers = sort_peer_ids_by_distance(
                target_key, list(dict.fromkeys(closest_peers))
            )[:count]

        queried_peers: set[ID] = set()
        rounds = 0
        start_time = trio.current_time()

        # Return early if we have no peers to start with
        if not closest_peers:
            logger.debug("No local peers available for network lookup")
            return []

        # Iterative lookup using a semaphore-based sliding window.
        # Instead of lock-step batches (start ALPHA, wait for ALL, repeat),
        # we keep up to ALPHA queries in flight at all times. When one finishes,
        # the next candidate starts immediately — no idle slots.
        #
        # Each round still picks a bounded set of candidates (up to `count`)
        # so that Kademlia's iterative refinement is preserved: after each
        # round we re-sort and may discover closer peers for the next round.
        sem = trio.Semaphore(ALPHA)
        new_peers: list[ID] = []
        query_count = 0

        async def _guarded_query(peer: ID) -> None:
            """Run a single peer query while holding one semaphore slot."""
            try:
                await self._query_single_peer_for_closest(peer, target_key, new_peers)
            finally:
                sem.release()

        while rounds < MAX_PEER_LOOKUP_ROUNDS:
            # Check total timeout (30 seconds max per spec recommendation)
            elapsed = trio.current_time() - start_time
            if elapsed > 30:
                logger.debug(
                    f"Lookup timed out after {elapsed:.1f}s, completed {rounds} rounds"
                )
                break

            rounds += 1
            logger.debug(f"Lookup round {rounds}/{MAX_PEER_LOOKUP_ROUNDS}")

            # Admit at most ALPHA peers per round to preserve classic Kademlia
            # iterative refinement: after each small batch we re-sort with any
            # newly discovered peers before admitting the next batch.
            # Exclude self - we can't query ourselves (Kubo does the same)
            local_id = self.host.get_id()
            peers_to_query = [
                p for p in closest_peers if p not in queried_peers and p != local_id
            ][:ALPHA]
            if not peers_to_query:
                logger.debug("No more unqueried peers available, ending lookup")
                break

            new_peers.clear()

            async with trio.open_nursery() as nursery:
                for peer in peers_to_query:
                    await sem.acquire()
                    queried_peers.add(peer)
                    query_count += 1
                    nursery.start_soon(_guarded_query, peer)

            # If we got no new peers, we're done
            if not new_peers:
                logger.debug("No new peers discovered in this round, ending lookup")
                break

            # Update our list of closest peers
            all_candidates = list(dict.fromkeys(closest_peers + new_peers))
            old_closest_peers = closest_peers[:]
            closest_peers = sort_peer_ids_by_distance(target_key, all_candidates)[
                :count
            ]
            logger.debug(f"Updated closest peers count: {len(closest_peers)}")

            # Check if we made any progress (found closer peers)
            if closest_peers == old_closest_peers:
                logger.debug("No improvement in closest peers, ending lookup")
                break

            # Beta resiliency: ensure at least BETA of the closest peers
            # have been queried before terminating
            queried_in_closest = sum(
                1 for p in closest_peers[:BUCKET_SIZE] if p in queried_peers
            )
            if queried_in_closest < BETA and len(closest_peers) >= BETA:
                # Not enough closest peers queried, continue if we have candidates
                unqueried_closest = [
                    p
                    for p in closest_peers[:BUCKET_SIZE]
                    if p not in queried_peers and p != local_id
                ]
                if unqueried_closest:
                    logger.debug(
                        f"Only {queried_in_closest}/{BETA} closest peers queried, "
                        "continuing lookup"
                    )
                    continue

        logger.info(
            f"Network lookup completed after {rounds} rounds "
            f"({query_count} queries), found {len(closest_peers)} peers"
        )
        return closest_peers

    async def _query_peer_for_closest(self, peer: ID, target_key: bytes) -> list[ID]:
        """
        Query a peer for their closest peers to the target key using varint
        length prefix. Each operation has a timeout to prevent hanging on
        unresponsive peers.
        """
        local_id = self.host.get_id()
        if peer == local_id:
            logger.debug("Skipping FIND_NODE query to ourselves")
            return []

        stream = None
        results = []
        try:
            with trio.move_on_after(QUERY_TIMEOUT):
                # Add the peer to our routing table regardless of query outcome
                try:
                    addrs = self.host.get_peerstore().addrs(peer)
                    if addrs:
                        peer_info = PeerInfo(peer, addrs)
                        await self.routing_table.add_peer(peer_info)
                except Exception as e:
                    logger.debug(f"Failed to add peer {peer} to routing table: {e}")

                # Open a stream to the peer using the Kademlia protocol
                logger.debug(f"Opening stream to {peer} for closest peers query")
                try:
                    stream = await self.host.new_stream(peer, [PROTOCOL_ID])
                    logger.debug(f"Stream opened to {peer}")
                except Exception as e:
                    logger.warning(f"Failed to open stream to {peer}: {e}")
                    # Per spec: remove peer from routing table if connection fails
                    self.routing_table.remove_peer(peer)
                    return []

                # Create and send FIND_NODE request using protobuf
                find_node_msg = Message()
                find_node_msg.type = Message.MessageType.FIND_NODE
                find_node_msg.key = target_key  # Set target key directly as bytes

                # Create sender_signed_peer_record
                envelope_bytes, _ = env_to_send_in_RPC(self.host)
                find_node_msg.senderRecord = envelope_bytes

                # Serialize and send the protobuf message with varint length prefix
                proto_bytes = find_node_msg.SerializeToString()
                logger.debug(
                    f"Sending FIND_NODE: {proto_bytes.hex()} (len={len(proto_bytes)})"
                )
                await stream.write(varint.encode(len(proto_bytes)))
                await stream.write(proto_bytes)

                # Read varint-prefixed response length with max byte limit

                length_bytes = b""
                max_varint_bytes = 10
                while True:
                    b = await stream.read(1)
                    if not b:
                        logger.warning(
                            "Error reading varint length from stream: connection closed"
                        )
                        return []
                    length_bytes += b
                    if b[0] & 0x80 == 0:
                        break
                    if len(length_bytes) >= max_varint_bytes:
                        logger.warning(
                            "Varint length exceeds maximum bytes, ignoring response"
                        )
                        return []
                response_length = varint.decode_bytes(length_bytes)

                # Read response data
                response_bytes = b""
                remaining = response_length
                while remaining > 0:
                    chunk = await stream.read(remaining)
                    if not chunk:
                        logger.debug(
                            f"Connection closed by peer {peer} while reading data"
                        )
                        return []
                    response_bytes += chunk
                    remaining -= len(chunk)

                # Parse the protobuf response
                response_msg = Message()
                response_msg.ParseFromString(response_bytes)
                logger.debug(
                    "Received response from %s with %d peers",
                    peer,
                    len(response_msg.closerPeers),
                )

                # Process closest peers from response
                if response_msg.type == Message.MessageType.FIND_NODE:
                    # Consume the sender_signed_peer_record
                    if not maybe_consume_signed_record(response_msg, self.host, peer):
                        logger.error(
                            "Received an invalid-signed-record, ignoring the response"
                        )
                        # Remove peer for sending invalid signed record
                        self.routing_table.remove_peer(peer)
                        return []

                    for peer_data in response_msg.closerPeers:
                        # Consume the received closer_peers signed-records,
                        # peer-id is sent with the peer-data
                        if not maybe_consume_signed_record(peer_data, self.host):
                            logger.warning(
                                "Received an invalid-signed-record, skipping peer"
                            )
                            continue

                        if not peer_data.id:
                            logger.debug("Skipping peer with empty ID in FIND_NODE")
                            continue

                        new_peer_id = ID(peer_data.id)
                        if new_peer_id == local_id:
                            continue
                        if new_peer_id not in results:
                            results.append(new_peer_id)
                        if peer_data.addrs:
                            from multiaddr import (
                                Multiaddr,
                            )

                            addrs = []
                            for addr_bytes in peer_data.addrs:
                                try:
                                    addrs.append(Multiaddr(addr_bytes))
                                except Exception:
                                    pass  # Skip invalid addresses
                            if addrs:
                                self.host.get_peerstore().add_addrs(
                                    new_peer_id, addrs, 3600
                                )
                                try:
                                    await self.routing_table.add_peer(
                                        PeerInfo(new_peer_id, addrs)
                                    )
                                except Exception as e:
                                    logger.debug(
                                        f"Failed to add discovered peer "
                                        f"{new_peer_id} to routing table: {e}"
                                    )

        except Exception as e:
            logger.debug(f"Error querying peer {peer} for closest: {e}")

        finally:
            if stream:
                await stream.close()
        return results

    async def refresh_routing_table(self) -> None:
        """
        Refresh the routing table by performing lookups for random keys.

        Per spec: "On every run, we generate a random peer ID for every
        non-empty routing table's k-bucket and we look it up."
        Also includes a lookup for the local peer ID.

        Returns
        -------
        None

        """
        logger.info("Refreshing routing table")

        # Perform a lookup for ourselves to populate the routing table
        local_id = self.host.get_id()
        closest_peers = await self.find_closest_peers_network(local_id.to_bytes())

        # Add discovered peers to routing table
        for peer_id in closest_peers:
            try:
                addrs = self.host.get_peerstore().addrs(peer_id)
                if addrs:
                    peer_info = PeerInfo(peer_id, addrs)
                    await self.routing_table.add_peer(peer_info)
            except Exception as e:
                logger.debug(f"Failed to add discovered peer {peer_id}: {e}")

        # Per spec: generate a random peer ID for every non-empty k-bucket
        # and look it up to discover new peers
        for bucket in self.routing_table.buckets:
            if bucket.size() > 0:
                # Generate a random peer ID that would fall in this bucket's range
                random_key = os.urandom(32)
                try:
                    random_peers = await self.find_closest_peers_network(random_key)
                    for peer_id in random_peers:
                        try:
                            addrs = self.host.get_peerstore().addrs(peer_id)
                            if addrs:
                                peer_info = PeerInfo(peer_id, addrs)
                                await self.routing_table.add_peer(peer_info)
                        except Exception as e:
                            logger.debug(
                                f"Failed to add peer {peer_id} during refresh: {e}"
                            )
                except Exception as e:
                    logger.debug(f"Failed to lookup random key for bucket refresh: {e}")
