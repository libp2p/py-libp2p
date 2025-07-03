import logging

from multiaddr import (
    Multiaddr,
)
import trio

from libp2p.abc import (
    IHost,
    INetStream,
    IPeerStore,
)
from libp2p.crypto.serialization import (
    deserialize_public_key,
)
from libp2p.custom_types import (
    StreamHandlerFn,
    TProtocol,
)
from libp2p.network.stream.exceptions import (
    StreamClosed,
)
from libp2p.peer.id import (
    ID,
)
from libp2p.utils import (
    get_agent_version,
)

from ..identify.identify import (
    _mk_identify_protobuf,
)
from ..identify.pb.identify_pb2 import (
    Identify,
)

logger = logging.getLogger(__name__)

# Protocol ID for identify/push
ID_PUSH = TProtocol("/ipfs/id/push/1.0.0")
PROTOCOL_VERSION = "ipfs/0.1.0"
AGENT_VERSION = get_agent_version()
CONCURRENCY_LIMIT = 10


def identify_push_handler_for(host: IHost) -> StreamHandlerFn:
    """
    Create a handler for the identify/push protocol.

    This handler receives pushed identify messages from remote peers and updates
    the local peerstore with the new information.
    """

    async def handle_identify_push(stream: INetStream) -> None:
        peer_id = stream.muxed_conn.peer_id

        try:
            # Read the identify message from the stream
            data = await stream.read()
            identify_msg = Identify()
            identify_msg.ParseFromString(data)

            # Update the peerstore with the new information
            await _update_peerstore_from_identify(
                host.get_peerstore(), peer_id, identify_msg
            )

            logger.debug("Successfully processed identify/push from peer %s", peer_id)
        except StreamClosed:
            logger.debug(
                "Stream closed while processing identify/push from %s", peer_id
            )
        except Exception as e:
            logger.error("Error processing identify/push from %s: %s", peer_id, e)
        finally:
            # Close the stream after processing
            await stream.close()

    return handle_identify_push


async def _update_peerstore_from_identify(
    peerstore: IPeerStore, peer_id: ID, identify_msg: Identify
) -> None:
    """
    Update the peerstore with information from an identify message.

    This function handles partial updates, where only some fields may be present
    in the identify message.
    """
    # Update public key if present
    if identify_msg.HasField("public_key"):
        try:
            # Note: This assumes the peerstore has a method to update the public key
            # You may need to adjust this based on your actual peerstore implementation
            peerstore.add_protocols(peer_id, [])
            # The actual public key update would go here
            pubkey = deserialize_public_key(identify_msg.public_key)
            peerstore.add_pubkey(peer_id, pubkey)
        except Exception as e:
            logger.error("Error updating public key for peer %s: %s", peer_id, e)

    # Update listen addresses if present
    if identify_msg.listen_addrs:
        try:
            # Convert bytes to Multiaddr objects
            addrs = [Multiaddr(addr) for addr in identify_msg.listen_addrs]
            # Add the addresses to the peerstore
            for addr in addrs:
                # Use a default TTL of 2 hours (7200 seconds)
                peerstore.add_addr(peer_id, addr, 7200)
        except Exception as e:
            logger.error("Error updating listen addresses for peer %s: %s", peer_id, e)

    # Update protocols if present
    if identify_msg.protocols:
        try:
            # Add the protocols to the peerstore
            peerstore.add_protocols(peer_id, identify_msg.protocols)
        except Exception as e:
            logger.error("Error updating protocols for peer %s: %s", peer_id, e)

    # Update observed address if present
    if identify_msg.HasField("observed_addr") and identify_msg.observed_addr:
        try:
            # Convert bytes to Multiaddr object
            observed_addr = Multiaddr(identify_msg.observed_addr)
            # Add the observed address to the peerstore
            # Use a default TTL of 2 hours (7200 seconds)
            peerstore.add_addr(peer_id, observed_addr, 7200)
        except Exception as e:
            logger.error("Error updating observed address for peer %s: %s", peer_id, e)


async def push_identify_to_peer(
    host: IHost,
    peer_id: ID,
    observed_multiaddr: Multiaddr | None = None,
    limit: trio.Semaphore = trio.Semaphore(CONCURRENCY_LIMIT),
) -> bool:
    """
    Push an identify message to a specific peer.

    This function opens a stream to the peer using the identify/push protocol,
    sends the identify message, and closes the stream.

    Returns
    -------
    bool
        True if the push was successful, False otherwise.

    """
    async with limit:
        try:
            # Create a new stream to the peer using the identify/push protocol
            stream = await host.new_stream(peer_id, [ID_PUSH])

            # Create the identify message
            identify_msg = _mk_identify_protobuf(host, observed_multiaddr)
            response = identify_msg.SerializeToString()

            # Send the identify message
            await stream.write(response)

            # Close the stream
            await stream.close()

            logger.debug("Successfully pushed identify to peer %s", peer_id)
            return True
        except Exception as e:
            logger.error("Error pushing identify to peer %s: %s", peer_id, e)
            return False


async def push_identify_to_peers(
    host: IHost,
    peer_ids: set[ID] | None = None,
    observed_multiaddr: Multiaddr | None = None,
) -> None:
    """
    Push an identify message to multiple peers in parallel.

    If peer_ids is None, push to all connected peers.
    """
    if peer_ids is None:
        # Get all connected peers
        peer_ids = set(host.get_connected_peers())

    # Push to each peer in parallel using a trio.Nursery
    # limiting concurrent connections to 10
    async with trio.open_nursery() as nursery:
        for peer_id in peer_ids:
            nursery.start_soon(push_identify_to_peer, host, peer_id, observed_multiaddr)
