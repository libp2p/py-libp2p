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
    StreamReset,
)
from libp2p.stream_muxer.exceptions import MuxedStreamError
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

def _safe_parse_multiaddr_cached(raw: bytes) -> Multiaddr | None:
    try:
        return Multiaddr(raw)
    except Exception:
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
            with trio.fail_after(10.0):
                data = await read_length_prefixed_protobuf(stream, use_varint_format)

            identify_msg = Identify()
            identify_msg.ParseFromString(data)

            # Update the peerstore with the new information
            await _update_peerstore_from_identify(
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


def _is_public_addr(a: Multiaddr) -> bool:
    """Return True if the multiaddr is a globally routable address."""
    s = str(a)
    # IPv4: unspecified, loopback, private, link-local, CGNAT, multicast
    if "/ip4/0." in s:
        return False
    if "/ip4/127." in s:
        return False
    if "/ip4/10." in s:
        return False
    if "/ip4/192.168." in s:
        return False
    if "/ip4/169.254." in s:   # link-local (RFC 3927)
        return False
    # 172.16.0.0/12 - use value_for_protocol for reliable IP extraction
    if "/ip4/172." in s:
        try:
            ip_str = a.value_for_protocol(4)
            parts = ip_str.split(".")
            if len(parts) == 4 and parts[0] == "172":
                second = int(parts[1])
                if 16 <= second <= 31:
                    return False
        except Exception:
            pass
    # CGNAT 100.64.0.0/10 (RFC 6598)
    if "/ip4/100." in s:
        try:
            ip_str = a.value_for_protocol(4)
            parts = ip_str.split(".")
            if len(parts) == 4 and parts[0] == "100":
                second = int(parts[1])
                if 64 <= second <= 127:
                    return False
        except Exception:
            pass
    # IPv4 multicast 224.0.0.0/4
    if "/ip4/224." in s or "/ip4/225." in s or "/ip4/226." in s or "/ip4/227." in s:
        return False
    if "/ip4/228." in s or "/ip4/229." in s or "/ip4/230." in s or "/ip4/231." in s:
        return False
    if "/ip4/232." in s or "/ip4/233." in s or "/ip4/234." in s or "/ip4/235." in s:
        return False
    if "/ip4/236." in s or "/ip4/237." in s or "/ip4/238." in s or "/ip4/239." in s:
        return False
    # IPv6: unspecified, loopback, link-local, ULA
    if "/ip6/::" in s:
        return False
    if "/ip6/::1" in s:
        return False
    if "/ip6/fe80" in s.lower():  # fe80::/10 link-local
        return False
    # IPv6 Unique Local Addresses (fc00::/7)
    if "/ip6/fc" in s.lower() or "/ip6/fd" in s.lower():
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
                    "Public key from %s does not hash to their peer ID (got %s). Ignoring key.",
                    peer_id,
                    derived_id,
                )
            else:
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

            # Replace old addresses: clear before adding new ones
            # The peer is the authoritative source for its own addresses
            try:
                peerstore.clear_addrs(peer_id)
            except Exception:
                pass  # Peer might not exist yet; that's fine
                
            for addr in addrs:
                peerstore.add_addr(peer_id, addr, 7200)  # 2 hours TTL
        except Exception as e:
            logger.error("Error updating listen addresses for peer %s: %s", peer_id, e)

    # Update protocols if present
    if identify_msg.protocols:
        try:
            # Replace old protocols: clear before adding new ones
            # The peer is the authoritative source for its own protocols
            try:
                peerstore.clear_protocol_data(peer_id)
            except Exception:
                pass  # Peer might not exist yet; that's fine
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
                # Reject forged record - peer ID mismatch, but continue parsing the rest
            else:
                if not peerstore.consume_peer_record(envelope, 7200):
                    logger.error(
                        "Updating Certified-Addr-Book was unsuccessful for %s", peer_id
                    )
        except Exception as e:
            logger.error(
                "Error updating the certified addr book for peer %s: %s", peer_id, e
            )




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
