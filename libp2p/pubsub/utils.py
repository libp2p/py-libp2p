import logging
import re

from libp2p.abc import IHost
from libp2p.peer.envelope import consume_envelope
from libp2p.peer.id import ID
from libp2p.pubsub.pb.rpc_pb2 import RPC

logger = logging.getLogger(__name__)
_BYTES_LITERAL_PATTERN: str = r"""(?:b'(?:[^'\\]|\\.)*'|b"(?:[^"\\]|\\.)*")"""
_CONTROL_MESSAGE_ID_PATTERN: re.Pattern[str] = re.compile(
    rf"^\({_BYTES_LITERAL_PATTERN}, {_BYTES_LITERAL_PATTERN}\)$"
)


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
            envelope, record = consume_envelope(msg.senderRecord, "libp2p-peer-record")
            if not record.peer_id == peer_id:
                return False

            if not host.get_peerstore().consume_peer_record(envelope, 7200):
                logger.error("Failed to update the Certified-Addr-Book")
                return False
        except Exception as e:
            logger.error("Failed to update the Certified-Addr-Book: %s", e)
            return False
    return True


def format_control_message_id(mid: tuple[bytes, bytes]) -> str:
    return str(mid)


def normalize_control_message_id(control_id: str | bytes) -> str:
    if isinstance(control_id, bytes):
        try:
            control_id = control_id.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError(f"invalid control message ID: {control_id!r}") from error
    return control_id


def validate_control_message_id(control_id: str | bytes) -> str:
    normalized = normalize_control_message_id(control_id)
    if not _CONTROL_MESSAGE_ID_PATTERN.fullmatch(normalized):
        raise ValueError(f"invalid control message ID: {normalized!r}")
    return normalized
