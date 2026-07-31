import logging

from multiaddr import (
    Multiaddr,
)
import trio

from libp2p.abc import (
    IHost,
    INetStream,
)
from libp2p.custom_types import (
    StreamHandlerFn,
    TProtocol,
)
from libp2p.identity.identify.identify import (
    _mk_identify_protobuf,
)
from libp2p.identity.identify.pb.identify_pb2 import (
    Identify,
)
from libp2p.identity.update import (
    update_peerstore_from_identify,
)
from libp2p.network.stream.exceptions import (
    StreamClosed,
    StreamReset,
)
from libp2p.stream_muxer.exceptions import MuxedStreamError
from libp2p.peer.id import (
    ID,
)
from libp2p.utils import (
    varint,
)
from libp2p.utils.varint import (
    read_length_prefixed_protobuf,
)

logger = logging.getLogger(__name__)

# Protocol ID for identify/push
ID_PUSH = TProtocol("/ipfs/id/push/1.0.0")
CONCURRENCY_LIMIT = 10


def identify_push_handler_for(
    host: IHost, use_varint_format: bool = True
) -> StreamHandlerFn:
    """
    Create a handler for the identify/push protocol.

    This handler receives pushed identify messages from remote peers and updates
    the local peerstore with the new information.

    Args:
        host: The libp2p host.
        use_varint_format: True=length-prefixed, False=raw protobuf.

    """

    async def handle_identify_push(stream: INetStream) -> None:
        peer_id = stream.muxed_conn.peer_id

        try:
            # Use the utility function to read the protobuf message
            with trio.fail_after(10.0):
                data = await read_length_prefixed_protobuf(stream, use_varint_format)

            identify_msg = Identify()
            identify_msg.ParseFromString(data)

            # Update the peerstore with the new information
            await update_peerstore_from_identify(
                host.get_peerstore(), peer_id, identify_msg
            )

            logger.debug("Successfully processed identify/push from peer %s", peer_id)

        except (StreamClosed, StreamReset):
            logger.debug(
                "Stream closed/reset while processing identify/push from %s", peer_id
            )
        except MuxedStreamError:
            logger.debug(
                "Muxed stream error while processing identify/push from %s", peer_id
            )
            try:
                await stream.reset()
            except Exception:
                pass
        except Exception as e:
            logger.error("Error processing identify/push from %s: %s", peer_id, e)
        finally:
            # Close the stream after processing
            try:
                await stream.close()
            except Exception:
                pass  # Ignore errors when closing

    return handle_identify_push


async def push_identify_to_peer(
    host: IHost,
    peer_id: ID,
    observed_multiaddr: Multiaddr | None = None,
    limit: trio.Semaphore | None = None,
    use_varint_format: bool = True,
) -> bool:
    """
    Push an identify message to a specific peer.

    This function opens a stream to the peer using the identify/push protocol,
    sends the identify message, and closes the stream.

    Args:
        host: The libp2p host.
        peer_id: The peer ID to push to.
        observed_multiaddr: The observed multiaddress (optional).
        limit: Semaphore for concurrency control.
        use_varint_format: True=length-prefixed, False=raw protobuf.

    Returns:
        bool: True if the push was successful, False otherwise.

    """
    if limit is None:
        limit = trio.Semaphore(CONCURRENCY_LIMIT)
    async with limit:
        stream = None
        try:
            # Create a new stream to the peer using the identify/push protocol
            stream = await host.new_stream(peer_id, [ID_PUSH])

            # Create the identify message
            identify_msg = _mk_identify_protobuf(host, observed_multiaddr)
            response = identify_msg.SerializeToString()

            if use_varint_format:
                # Combine length prefix and response into a single write to avoid races
                length_prefix = varint.encode_uvarint(len(response))
                await stream.write(length_prefix + response)
            else:
                # Send raw protobuf message
                await stream.write(response)

            # Per the identify-push spec, the receiver should NOT reply;
            # just close the stream after sending.
            await stream.close()
            stream = None

            logger.debug("Successfully pushed identify to peer %s", peer_id)
            return True
        except Exception as e:
            logger.error("Error pushing identify to peer %s: %s", peer_id, e)
            if stream is not None:
                try:
                    await stream.reset()
                except Exception:
                    pass
            return False


async def push_identify_to_peers(
    host: IHost,
    peer_ids: set[ID] | None = None,
    observed_multiaddr: Multiaddr | None = None,
    use_varint_format: bool = True,
) -> None:
    """
    Push an identify message to multiple peers in parallel.

    If peer_ids is None, push to all connected peers.

    Args:
        host: The libp2p host.
        peer_ids: Set of peer IDs to push to (if None, push to all connected peers).
        observed_multiaddr: The observed multiaddress (optional).
        use_varint_format: True=length-prefixed, False=raw protobuf.

    """
    if peer_ids is None:
        # Get all connected peers
        peer_ids = set(host.get_connected_peers())

    # Create a single shared semaphore for concurrency control
    limit = trio.Semaphore(CONCURRENCY_LIMIT)

    # Push to each peer in parallel using a trio.Nursery
    # limiting concurrent connections to CONCURRENCY_LIMIT
    async with trio.open_nursery() as nursery:
        for peer_id in peer_ids:
            nursery.start_soon(
                push_identify_to_peer,
                host,
                peer_id,
                observed_multiaddr,
                limit,
                use_varint_format,
            )
