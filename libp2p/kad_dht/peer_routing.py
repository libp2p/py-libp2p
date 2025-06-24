"""
Peer routing implementation for Kademlia DHT.

This module implements the peer routing interface using Kademlia's algorithm
to efficiently locate peers in a distributed network.
"""

import logging

import trio
import varint

from libp2p.abc import (
    IHost,
    INetStream,
    IPeerRouting,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.peer.peerinfo import (
    PeerInfo,
)

from .common import (
    ALPHA,
    PROTOCOL_ID,
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

# logger = logging.getLogger("libp2p.kademlia.peer_routing")
logger = logging.getLogger("kademlia-example.peer_routing")

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

        Returns
        -------
        list[ID]
            Closest peer IDs

        """
        # Start with closest peers from our routing table
        closest_peers = self.routing_table.find_local_closest_peers(target_key, count)
        logger.debug("Local closest peers: %d found", len(closest_peers))
        queried_peers: set[ID] = set()
        rounds = 0

        # Return early if we have no peers to start with
        if not closest_peers:
            logger.warning("No local peers available for network lookup")
            return []

        # Iterative lookup until convergence
        while rounds < MAX_PEER_LOOKUP_ROUNDS:
            rounds += 1
            logger.debug(f"Lookup round {rounds}/{MAX_PEER_LOOKUP_ROUNDS}")

            # Find peers we haven't queried yet
            peers_to_query = [p for p in closest_peers if p not in queried_peers]
            if not peers_to_query:
                logger.debug("No more unqueried peers available, ending lookup")
                break  # No more peers to query

            # Query these peers for their closest peers to target
            peers_batch = peers_to_query[:ALPHA]  # Limit to ALPHA peers at a time

            # Mark these peers as queried before we actually query them
            for peer in peers_batch:
                queried_peers.add(peer)

            # Run queries in parallel for this batch using trio nursery
            new_peers: list[ID] = []  # Shared array to collect all results

            async with trio.open_nursery() as nursery:
                for peer in peers_batch:
                    nursery.start_soon(
                        self._query_single_peer_for_closest, peer, target_key, new_peers
                    )

            # If we got no new peers, we're done
            if not new_peers:
                logger.debug("No new peers discovered in this round, ending lookup")
                break

            # Update our list of closest peers
            all_candidates = closest_peers + new_peers
            old_closest_peers = closest_peers[:]
            closest_peers = sort_peer_ids_by_distance(target_key, all_candidates)[
                :count
            ]
            logger.debug(f"Updated closest peers count: {len(closest_peers)}")

            # Check if we made any progress (found closer peers)
            if closest_peers == old_closest_peers:
                logger.debug("No improvement in closest peers, ending lookup")
                break

        logger.info(
            f"Network lookup completed after {rounds} rounds, "
            f"found {len(closest_peers)} peers"
        )
        return closest_peers

    async def _query_peer_for_closest(self, peer: ID, target_key: bytes) -> list[ID]:
        """
        Query a peer for their closest peers
        to the target key using varint length prefix
        """
        stream = None
        results = []
        try:
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
                return []

            # Create and send FIND_NODE request using protobuf
            find_node_msg = Message()
            find_node_msg.type = Message.MessageType.FIND_NODE
            find_node_msg.key = target_key  # Set target key directly as bytes

            # Serialize and send the protobuf message with varint length prefix
            proto_bytes = find_node_msg.SerializeToString()
            logger.debug(
                f"Sending FIND_NODE: {proto_bytes.hex()} (len={len(proto_bytes)})"
            )
            await stream.write(varint.encode(len(proto_bytes)))
            await stream.write(proto_bytes)

            # Read varint-prefixed response length
            length_bytes = b""
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
            response_length = varint.decode_bytes(length_bytes)

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
            logger.debug(
                "Received response from %s with %d peers",
                peer,
                len(response_msg.closerPeers),
            )

            # Process closest peers from response
            if response_msg.type == Message.MessageType.FIND_NODE:
                for peer_data in response_msg.closerPeers:
                    new_peer_id = ID(peer_data.id)
                    if new_peer_id not in results:
                        results.append(new_peer_id)
                    if peer_data.addrs:
                        from multiaddr import (
                            Multiaddr,
                        )

                        addrs = [Multiaddr(addr) for addr in peer_data.addrs]
                        self.host.get_peerstore().add_addrs(new_peer_id, addrs, 3600)

        except Exception as e:
            logger.debug(f"Error querying peer {peer} for closest: {e}")

        finally:
            if stream:
                await stream.close()
        return results

    async def _handle_kad_stream(self, stream: INetStream) -> None:
        """
        Handle incoming Kademlia protocol streams.

        params: stream: The incoming stream

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
