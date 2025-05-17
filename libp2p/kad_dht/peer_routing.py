"""
Peer routing implementation for Kademlia DHT.

This module implements the peer routing interface using Kademlia's algorithm
to efficiently locate peers in a distributed network.
"""

import logging
from typing import (
    Optional,
)

# Remove json import and add protobuf imports
from libp2p.abc import (
    IHost,
    INetStream,
    IPeerRouting,
)
from libp2p.custom_types import (
    TProtocol,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.peer.peerinfo import (
    PeerInfo,
)

from .pb.kademlia_pb2 import (
    Message,
)
from .routing_table import (
    RoutingTable,
)
from .utils import (
    sort_peer_ids_by_distance,
)

logger = logging.getLogger("libp2p.kademlia.peer_routing")

# Constants for the Kademlia algorithm
ALPHA = 3  # Concurrency parameter
MAX_PEER_LOOKUP_ROUNDS = 20  # Maximum number of rounds in peer lookup


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
        self.protocol_id = TProtocol("/ipfs/kad/1.0.0")
        # Register protocol handler for incoming requests
        self.host.set_stream_handler(self.protocol_id, self._handle_kad_stream)

    async def find_peer(self, peer_id: ID) -> Optional[PeerInfo]:
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

        except Exception as e:
            logger.error(f"Error searching for peer {peer_id}: {e}")

        # Not found
        logger.info(f"Peer {peer_id} not found")
        return None

    async def find_closest_peers_network(
        self, target_key: bytes, count: int = 20
    ) -> list[ID]:
        """
        Find the closest peers to a target key in the entire network.

        Performs an iterative lookup by querying peers for their closest peers.

        Returns
        -------
        list[ID]
            Closest peer IDs

        """
        # Start with closest peers from our routing table
        closest_peers = self.routing_table.find_local_closest_peers(target_key, count)
        logger.info("local closest peers are %s", closest_peers)
        queried_peers = set()

        # Iterative lookup until convergence
        while True:
            # Find peers we haven't queried yet
            peers_to_query = [p for p in closest_peers if p not in queried_peers]
            if not peers_to_query:
                break  # No more peers to query

            # Query these peers for their closest peers to target
            new_peers = []
            for peer in peers_to_query[:ALPHA]:  # Query ALPHA peers at a time
                queried_peers.add(peer)
                try:
                    peer_results = await self._query_peer_for_closest(peer, target_key)
                    logger.info(
                        "Queried peer %s for closest peers, got %d results",
                        peer,
                        len(peer_results),
                    )
                    new_peers.extend(peer_results)
                except Exception:
                    continue  # Skip failed queries

            # Update our list of closest peers
            all_candidates = closest_peers + new_peers
            closest_peers = sort_peer_ids_by_distance(target_key, all_candidates)[
                :count
            ]
            logger.info(f"Updated closest peers: {closest_peers}")

            # Check if we found any closer peers in this round
            if all(p in queried_peers for p in closest_peers[:ALPHA]):
                break  # No improvement, we're done

        return closest_peers

    async def _query_peer_for_closest(self, peer: ID, target_key: bytes) -> list[ID]:
        """
        Query a peer for their closest peers to the target key.

        Args:
        ----
            peer: The peer to query
            target_key: The target key to find closest peers for

        Returns
        -------
        List[ID]
            List of peer IDs that are closest to the target key

        """
        stream = None
        results = []
        try:
            # Add the peer to our routing table regardless of query outcome
            try:
                # Create PeerInfo from ID to add to routing table
                addrs = self.host.get_peerstore().addrs(peer)
                if addrs:
                    peer_info = PeerInfo(peer, addrs)
                    await self.routing_table.add_peer(peer_info)
            except Exception as e:
                logger.debug(f"Failed to add peer {peer} to routing table: {e}")

            # Open a stream to the peer using the Kademlia protocol
            logger.info(f"Opening stream to {peer} for closest peers query")
            try:
                stream = await self.host.new_stream(peer, [self.protocol_id])
                logger.info(f"Stream opened to {peer}")
            except Exception as e:
                logger.error(f"Failed to open stream to {peer}: {e}")
                return []

            # Create and send FIND_NODE request using protobuf
            find_node_msg = Message()
            find_node_msg.type = Message.MessageType.FIND_NODE
            find_node_msg.key = target_key  # Set target key directly as bytes

            # Serialize and send the protobuf message with length prefix
            proto_bytes = find_node_msg.SerializeToString()
            await stream.write(len(proto_bytes).to_bytes(4, "big"))
            await stream.write(proto_bytes)

            # Read response length (4 bytes)
            length_bytes = b""
            remaining = 4
            while remaining > 0:
                try:
                    chunk = await stream.read(remaining)
                except Exception as e:
                    logger.warning(f"Error reading from stream: {e}")
                    return []

                if not chunk:
                    logger.debug(
                        f"Connection closed by peer {peer} while reading length"
                    )
                    return []

                length_bytes += chunk
                remaining -= len(chunk)

            response_length = int.from_bytes(length_bytes, byteorder="big")

            # Read response data
            response_bytes = b""
            remaining = response_length
            while remaining > 0:
                chunk = await stream.read(remaining)
                if not chunk:
                    logger.debug(f"Connection closed by peer {peer} while reading data")
                    return []

                response_bytes += chunk
                remaining -= len(chunk)

            # Parse the protobuf response
            response_msg = Message()
            response_msg.ParseFromString(response_bytes)
            logger.info(
                "Received response from %s with %d peers",
                peer,
                len(response_msg.closerPeers),
            )

            # Process closest peers from response
            if response_msg.type == Message.MessageType.FIND_NODE:
                for peer_data in response_msg.closerPeers:
                    # Create peer ID from returned data
                    new_peer_id = ID(peer_data.id)

                    # Add to results if not already present
                    if new_peer_id not in results:
                        results.append(new_peer_id)

                    # Store peer addresses in peerstore if provided
                    if peer_data.addrs:
                        from multiaddr import (
                            Multiaddr,
                        )

                        addrs = [Multiaddr(addr) for addr in peer_data.addrs]
                        self.host.get_peerstore().add_addrs(new_peer_id, addrs, 3600)

            return results

        except Exception as e:
            logger.debug(f"Error querying peer {peer} for closest: {e}")
            return []

        finally:
            # Ensure stream is closed even if an exception occurs
            if stream:
                await stream.close()

    async def find_closest_peers(self, peer_id: ID, count: int = 20) -> list[ID]:
        """
        Find the closest peers to a given peer ID.

        Args:
        ----
            peer_id: The target peer ID
            count: Maximum number of peers to return

        Returns
        -------
        List[ID]
            List of closest peer IDs

        """
        target_key = peer_id.to_bytes()

        # Get initial set of peers to query from our routing table
        initial_peers = self.routing_table.find_local_closest_peers(target_key, ALPHA)
        if not initial_peers:
            logger.debug("No peers in routing table to start lookup")
            return []

        # Prepare sets for the algorithm
        queried_peers: set[ID] = set()
        pending_peers: set[ID] = set(initial_peers)
        closest_peers: list[ID] = initial_peers.copy()

        # Kademlia iterative lookup
        for _ in range(MAX_PEER_LOOKUP_ROUNDS):
            if not pending_peers:
                break

            # Select alpha peers to query in this round
            peers_to_query = list(pending_peers)[:ALPHA]
            for peer in peers_to_query:
                pending_peers.remove(peer)
                queried_peers.add(peer)

            # Query selected peers in parallel
            new_peers = await self._query_peers_for_closer_peers(
                peers_to_query, target_key
            )

            # Update our closest peers list
            for new_peer in new_peers:
                if new_peer not in queried_peers and new_peer not in pending_peers:
                    pending_peers.add(new_peer)
                    closest_peers.append(new_peer)

            # Keep the closest peers only
            closest_peers = self.routing_table.find_local_closest_peers(
                target_key, count
            )

            # If we haven't found any new closer peers, we can stop
            if all(peer in queried_peers for peer in closest_peers):
                break

        logger.debug(f"Found {len(closest_peers)} peers close to {peer_id}")
        return closest_peers

    async def _handle_kad_stream(self, stream: INetStream) -> None:
        """
        Handle incoming Kademlia protocol streams.

        Args:
        ----
            stream: The incoming stream

        Returns
        -------
        None

        """
        try:
            # Read message length
            length_bytes = await stream.read(4)
            if not length_bytes:
                return

            message_length = int.from_bytes(length_bytes, byteorder="big")

            # Read message
            message_bytes = await stream.read(message_length)
            if not message_bytes:
                return

            # Parse protobuf message
            kad_message = Message()
            try:
                kad_message.ParseFromString(message_bytes)

                if kad_message.type == Message.MessageType.FIND_NODE:
                    # Get target key directly from protobuf message
                    target_key = kad_message.key

                    # Find closest peers to target
                    closest_peers = self.routing_table.find_local_closest_peers(
                        target_key, 20
                    )

                    # Create protobuf response
                    response = Message()
                    response.type = Message.MessageType.FIND_NODE

                    # Add peer information to response
                    for peer_id in closest_peers:
                        peer_proto = response.closerPeers.add()
                        peer_proto.id = peer_id.to_bytes()
                        peer_proto.connection = Message.ConnectionType.CAN_CONNECT

                        # Add addresses if available
                        try:
                            addrs = self.host.get_peerstore().addrs(peer_id)
                            if addrs:
                                for addr in addrs:
                                    peer_proto.addrs.append(addr.to_bytes())
                        except Exception:
                            pass

                    # Send response
                    response_bytes = response.SerializeToString()
                    await stream.write(len(response_bytes).to_bytes(4, byteorder="big"))
                    await stream.write(response_bytes)

            except Exception as parse_err:
                logger.error(f"Failed to parse protocol buffer message: {parse_err}")

        except Exception as e:
            logger.debug(f"Error handling Kademlia stream: {e}")
        finally:
            await stream.close()

    async def bootstrap(self, bootstrap_peers: list[PeerInfo]) -> None:
        """
        Bootstrap the routing table with a list of known peers.

        Args:
        ----
            bootstrap_peers: List of known peers to start with

        Returns
        -------
        None

        """
        logger.info(f"Bootstrapping with {len(bootstrap_peers)} peers")

        # Add the bootstrap peers to the routing table
        for peer_info in bootstrap_peers:
            self.host.get_peerstore().add_addrs(
                peer_info.peer_id, peer_info.addrs, 3600
            )
            # Now properly await the async add_peer method
            await self.routing_table.add_peer(peer_info)

        # If we have bootstrap peers, refresh the routing table
        if bootstrap_peers:
            await self.refresh_routing_table()

    async def refresh_routing_table(self) -> None:
        """
        Refresh the routing table by performing lookups for random keys.

        Returns
        -------
        None

        """
        logger.info("Refreshing routing table")

        # Perform a lookup for ourselves to populate the routing table
        local_id = self.host.get_id()
        await self.find_closest_peers_network(local_id.to_bytes())

        # In a complete implementation, you would also refresh buckets
        # that haven't been updated recently
