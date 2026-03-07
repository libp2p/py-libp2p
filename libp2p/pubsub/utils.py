import ast
import logging

from libp2p.abc import IHost
from libp2p.custom_types import (
    MessageID,
)
from libp2p.peer.envelope import consume_envelope
from libp2p.peer.id import ID
from libp2p.pubsub.pb.rpc_pb2 import RPC

logger = logging.getLogger(__name__)


def maybe_consume_signed_record(msg: RPC, host: IHost, peer_id: ID) -> bool:
    """
    Attempt to parse and store a signed-peer-record (Envelope) received during
    PubSub communication. If the record is invalid, the peer-id does not match, or
    updating the peerstore fails, the function logs an error and returns False.

    Parameters
    ----------
    msg : RPC
        The protobuf message received during PubSub communication.
    host : IHost
        The local host instance, providing access to the peerstore for storing
        verified peer records.
    peer_id : ID | None, optional
        The expected peer ID for record validation. If provided, the peer ID
        inside the record must match this value.

    Returns
    -------
    bool
        True if a valid signed peer record was successfully consumed and stored,
        False otherwise.

    """
    if msg.HasField("senderRecord"):
        try:
            # Convert the signed-peer-record(Envelope) from
            # protobuf bytes
            envelope, record = consume_envelope(msg.senderRecord, "libp2p-peer-record")
            if not record.peer_id == peer_id:
                return False

            # Use the default TTL of 2 hours (7200 seconds)
            if not host.get_peerstore().consume_peer_record(envelope, 7200):
                logger.error("Failed to update the Certified-Addr-Book")
                return False
        except Exception as e:
            logger.error("Failed to update the Certified-Addr-Book: %s", e)
            return False
    return True


def parse_message_id_safe(msg_id: str | bytes) -> MessageID:
    """
    Safely handle message ID as string.

    Some peers may send non-text binary message IDs over string-typed protobuf
    fields. In that case we only accept UTF-8 decodable payloads and reject
    the rest so callers can skip invalid IDs without crashing.
    """
    if isinstance(msg_id, str):
        return MessageID(msg_id)
    if isinstance(msg_id, bytes):
        try:
            return MessageID(msg_id.decode("utf-8"))
        except UnicodeDecodeError as exc:
            raise ValueError("message ID is not UTF-8 decodable") from exc
    raise ValueError(f"unsupported message ID type: {type(msg_id)!r}")


def safe_parse_message_id(msg_id: str | bytes) -> tuple[bytes, bytes]:
    """
    Safely parse message ID using ast.literal_eval with validation.
    :param msg_id: String representation of message ID
    :return: Tuple of (seqno, from_id) as bytes
    :raises ValueError: If parsing fails
    """
    try:
        msg_id_str = msg_id.decode("utf-8") if isinstance(msg_id, bytes) else msg_id
        if not isinstance(msg_id_str, str):
            raise ValueError("Message ID must be str or UTF-8 bytes")

        parsed = ast.literal_eval(msg_id_str)
        if not isinstance(parsed, tuple) or len(parsed) != 2:
            raise ValueError("Invalid message ID format")

        seqno, from_id = parsed
        if not isinstance(seqno, bytes) or not isinstance(from_id, bytes):
            raise ValueError("Message ID components must be bytes")

        return (seqno, from_id)
    except (ValueError, SyntaxError, UnicodeDecodeError, TypeError) as e:
        raise ValueError(f"Invalid message ID format: {e}")


def safe_bytes_from_hex(hex_str: str) -> bytes | None:
    """
    Decode a hex-encoded string to bytes, returning None on failure.

    Used for defensively parsing wire message IDs in IHAVE/IWANT handlers
    so that malformed hex from peers does not crash the gossip handler task.
    """
    try:
        return bytes.fromhex(hex_str)
    except ValueError:
        return None
