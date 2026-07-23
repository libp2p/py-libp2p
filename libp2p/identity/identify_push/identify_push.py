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
from libp2p.peer.envelope import consume_envelope
from libp2p.peer.id import (
    ID,
)
from libp2p.utils import (
    get_agent_version,
    varint,
)
from libp2p.utils.varint import (
    read_length_prefixed_protobuf,
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

from collections import deque

_MAX_UNPARSEABLE_CACHE = 512
_UNPARSEABLE_ADDRS_CACHE: set[bytes] = set()
_UNPARSEABLE_ADDRS_ORDER: deque[bytes] = deque()


def _safe_parse_multiaddr_cached(raw: bytes) -> Multiaddr | None:
    if raw in _UNPARSEABLE_ADDRS_CACHE:
        return None
    try:
        return Multiaddr(raw)
    except Exception:
        if len(_UNPARSEABLE_ADDRS_CACHE) >= _MAX_UNPARSEABLE_CACHE:
            oldest = _UNPARSEABLE_ADDRS_ORDER.popleft()
            _UNPARSEABLE_ADDRS_CACHE.discard(oldest)
        _UNPARSEABLE_ADDRS_CACHE.add(raw)
        _UNPARSEABLE_ADDRS_ORDER.append(raw)
        logger.debug("Skipping unparseable multiaddr in identify: %r", raw[:64])
        return None


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
            data = await read_length_prefixed_protobuf(stream, use_varint_format)

            identify_msg = Identify()
            identify_msg.ParseFromString(data)

            # Update the peerstore with the new information
            await _update_peerstore_from_identify(
                host.get_peerstore(), peer_id, identify_msg
            )

            logger.debug("Successfully processed identify/push from peer %s", peer_id)

            # Send acknowledgment to indicate successful processing
            # This ensures the sender knows the message was received before closing
            await stream.write(b"OK")

        except StreamClosed:
            logger.debug(
                "Stream closed while processing identify/push from %s", peer_id
            )
        except Exception as e:
            logger.error("Error processing identify/push from %s: %s", peer_id, e)
        finally:
            # Close the stream after processing
            try:
                await stream.close()
            except Exception:
                pass  # Ignore errors when closing

    return handle_identify_push


def _is_public_addr(a: Multiaddr) -> bool:
    """Return True if the multiaddr is a globally routable address."""
    s = str(a)
    # IPv4 private/loopback/link-local
    if "/ip4/127." in s:
        return False
    if "/ip4/10." in s:
        return False
    if "/ip4/192.168." in s:
        return False
    if "/ip4/169.254." in s:   # link-local (RFC 3927)
        return False
    # 172.16.0.0/12
    if "/ip4/172." in s:
        try:
            ip = s.split("/")[2]
            parts = [int(p) for p in ip.split(".")]
            if parts[0] == 172 and 16 <= parts[1] <= 31:
                return False
        except Exception:
            pass
    # IPv6 loopback and link-local
    if "/ip6/::1" in s:
        return False
    if "/ip6/fe80" in s.lower():  # fe80::/10 link-local
        return False
    return True


async def _update_peerstore_from_identify(
    peerstore: IPeerStore, peer_id: ID, identify_msg: Identify
) -> None:
    """
    Update the peerstore with information from an identify message.

    This function handles partial updates, where only some fields may be present
    in the identify message.

    Security: Signed peer records are validated to ensure the peer ID in the
    record matches the sender's peer ID to prevent peer ID spoofing attacks.
    """
    # Update public key if present
    if identify_msg.HasField("public_key"):
        try:
            pubkey = deserialize_public_key(identify_msg.public_key)
            # Security: verify the key hashes to the claimed peer ID
            derived_id = ID.from_pubkey(pubkey)
            if derived_id != peer_id:
                logger.warning(
                    "Public key from %s does not hash to their peer ID (got %s). Ignoring.",
                    peer_id,
                    derived_id,
                )
                return
            peerstore.add_pubkey(peer_id, pubkey)
        except Exception as e:
            logger.error("Error updating public key for peer %s: %s", peer_id, e)

    # Update listen addresses if present
    if identify_msg.listen_addrs:
        try:
            MAX_LISTEN_ADDRS = 1000
            raw_addrs = identify_msg.listen_addrs
            if len(raw_addrs) > MAX_LISTEN_ADDRS:
                logger.warning(
                    "Peer %s sent %d listen addresses; truncating to %d",
                    peer_id, len(raw_addrs), MAX_LISTEN_ADDRS,
                )
                raw_addrs = raw_addrs[:MAX_LISTEN_ADDRS]

            addrs = []
            for addr_bytes in raw_addrs:
                ma = _safe_parse_multiaddr_cached(addr_bytes)
                if ma is not None:
                    addrs.append(ma)
            
            # Always filter private/loopback/link-local addresses
            addrs = [a for a in addrs if _is_public_addr(a)]
                
            for addr in addrs:
                peerstore.add_addr(peer_id, addr, 7200)  # 2 hours TTL
        except Exception as e:
            logger.error("Error updating listen addresses for peer %s: %s", peer_id, e)

    # Update protocols if present
    if identify_msg.protocols:
        try:
            peerstore.add_protocols(peer_id, identify_msg.protocols)
        except Exception as e:
            logger.error("Error updating protocols for peer %s: %s", peer_id, e)

    # Update from signed peer record if present
    if identify_msg.HasField("signedPeerRecord"):
        try:
            envelope, record = consume_envelope(
                identify_msg.signedPeerRecord, "libp2p-peer-record"
            )
            # Cross-check peer-id consistency
            # Security: Reject signed peer records where the peer ID doesn't match
            # the sender's peer ID to prevent peer ID spoofing attacks
            if record.peer_id != peer_id:
                logger.warning(
                    "SignedPeerRecord peer-id mismatch: record=%s, sender=%s. "
                    "Ignoring.",
                    record.peer_id,
                    peer_id,
                )
                return  # Reject forged record - peer ID mismatch

            if not peerstore.consume_peer_record(envelope, 7200):
                logger.error(
                    "Updating Certified-Addr-Book was unsuccessful for %s", peer_id
                )
        except Exception as e:
            logger.error(
                "Error updating the certified addr book for peer %s: %s", peer_id, e
            )

    # Update observed address if present
    if identify_msg.HasField("observed_addr") and identify_msg.observed_addr:
        try:
            observed_addr = Multiaddr(identify_msg.observed_addr)
            peerstore.add_addr(peer_id, observed_addr, 7200)
        except Exception as e:
            logger.error("Error updating observed address for peer %s: %s", peer_id, e)


async def push_identify_to_peer(
    host: IHost,
    peer_id: ID,
    observed_multiaddr: Multiaddr | None = None,
    limit: trio.Semaphore = trio.Semaphore(CONCURRENCY_LIMIT),
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
    async with limit:
        try:
            # Create a new stream to the peer using the identify/push protocol
            stream = await host.new_stream(peer_id, [ID_PUSH])

            # Create the identify message
            identify_msg = _mk_identify_protobuf(host, observed_multiaddr)
            response = identify_msg.SerializeToString()

            if use_varint_format:
                # Send length-prefixed identify message
                await stream.write(varint.encode_uvarint(len(response)))
                await stream.write(response)
            else:
                # Send raw protobuf message
                await stream.write(response)

            # Wait for acknowledgment from the receiver with timeout
            # This ensures the message was processed before closing
            try:
                with trio.move_on_after(1.0):  # 1 second timeout
                    ack = await stream.read(2)  # Read "OK" acknowledgment
                    if ack != b"OK":
                        logger.warning(
                            "Unexpected acknowledgment from peer %s: %s", peer_id, ack
                        )
            except Exception as e:
                logger.debug("No acknowledgment received from peer %s: %s", peer_id, e)
                # Continue anyway, as the message might have been processed

            # Close the stream after acknowledgment (or timeout)
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
