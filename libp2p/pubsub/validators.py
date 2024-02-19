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

    # Validate if message sender matches message signer,
    # i.e., check if `msg.key` matches `msg.from_id`
    msg_pubkey = deserialize_public_key(msg.key)
    if ID.from_pubkey(msg_pubkey) != msg.from_id:
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
