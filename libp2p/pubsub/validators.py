import logging

from libp2p.crypto.serialization import (
    deserialize_public_key,
)
from libp2p.peer.id import (
    ID,
)

from .pb import (
    rpc_pb2,
)

logger = logging.getLogger("libp2p.pubsub")

PUBSUB_SIGNING_PREFIX = "libp2p-pubsub:"


def signature_validator(msg: rpc_pb2.Message) -> bool:
    """
    Verify the message against the given public key.

    :param pubkey: the public key which signs the message.
    :param msg: the message signed.
    """
    # Check if signature is attached
    if msg.signature == b"":
        logger.debug("Reject because no signature attached for msg: %s", msg)
        return False

    # Get the public key - either from msg.key or extracted from peer ID
    # For Ed25519 and other small keys, the key is embedded in the peer ID
    # For RSA keys (which are too large), the key is sent in msg.key
    msg_pubkey = None
    sender_id = ID(msg.from_id)

    # First, try to extract public key from the peer ID (from_id)
    try:
        msg_pubkey = sender_id.extract_public_key()
        if msg_pubkey:
            logger.debug(
                "Extracted public key from peer ID, type: %s", msg_pubkey.get_type()
            )
    except Exception as e:
        logger.debug("Could not extract key from peer ID: %s", e)

    # If we couldn't extract from peer ID, use msg.key
    if msg_pubkey is None:
        if not msg.key or len(msg.key) == 0:
            logger.debug(
                "Reject because no key attached and cannot extract from peer "
                "ID for msg: %s",
                msg,
            )
            return False
        logger.debug(
            "Using msg.key for signature verification, length: %d", len(msg.key)
        )
        try:
            msg_pubkey = deserialize_public_key(msg.key)
        except Exception as e:
            logger.debug("Failed to deserialize public key: %s", e)
            raise
    if ID.from_pubkey(msg_pubkey) != sender_id:
        logger.debug(
            "Reject because signing key does not match sender ID for msg: %s", msg
        )
        return False
    # First, construct the original payload that's signed by 'msg.key'
    msg_without_key_sig = rpc_pb2.Message(
        data=msg.data, topicIDs=msg.topicIDs, from_id=msg.from_id, seqno=msg.seqno
    )
    payload = PUBSUB_SIGNING_PREFIX.encode() + msg_without_key_sig.SerializeToString()
    try:
        return msg_pubkey.verify(payload, msg.signature)
    except Exception:
        return False
