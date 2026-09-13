"""
Shared utilities for processing Identify messages.

This module contains the peerstore update logic used by both the identify
and identify/push handlers.
"""

import functools
import logging

from multiaddr import Multiaddr

from libp2p.abc import IPeerStore
from libp2p.crypto.serialization import deserialize_public_key
from libp2p.identity.identify.pb.identify_pb2 import Identify
from libp2p.peer.envelope import consume_envelope
from libp2p.peer.id import ID

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=1000)
def _safe_parse_multiaddr_cached(raw: bytes) -> Multiaddr | None:
    try:
        return Multiaddr(raw)
    except Exception:
        logger.debug("Skipping unparseable multiaddr in identify: %r", raw[:64])
        return None


async def update_peerstore_from_identify(
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
                    "Public key from %s does not hash to their peer ID "
                    "(got %s). Ignoring public key but continuing with "
                    "other fields.",
                    peer_id,
                    derived_id,
                )
                # Skip pubkey update but continue processing other fields
            else:
                peerstore.add_pubkey(peer_id, pubkey)
        except Exception as e:
            logger.error("Error updating public key for peer %s: %s", peer_id, e)

    # Update listen addresses if present
    if identify_msg.listen_addrs:
        try:
            MAX_LISTEN_ADDRS = 1000
            all_raw_addrs = identify_msg.listen_addrs
            raw_addrs: list[bytes] = list(all_raw_addrs)
            if len(raw_addrs) > MAX_LISTEN_ADDRS:
                logger.warning(
                    "Peer %s sent %d listen addresses; truncating to %d",
                    peer_id,
                    len(raw_addrs),
                    MAX_LISTEN_ADDRS,
                )
                raw_addrs = raw_addrs[:MAX_LISTEN_ADDRS]

            addrs = []
            for addr_bytes in raw_addrs:
                ma = _safe_parse_multiaddr_cached(addr_bytes)
                if ma is not None:
                    addrs.append(ma)

            # Store all advertised listen addresses, including private ones.
            # Filtering happens at dial time, not storage time (matching
            # go-libp2p). Dropping private addresses here breaks hole
            # punching: NAT'd peers can only be reached via the private
            # addresses their relayed/observed connections reveal, and
            # relay reservations must report usable addresses for strict
            # implementations to accept them.
            # Replace old addresses (peer is authoritative source for its own addrs)
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
            # Replace old protocols (peer is authoritative source for its own protocols)
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
