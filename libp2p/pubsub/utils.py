import ast

from libp2p.custom_types import (
    MessageID,
)


def parse_message_id_safe(msg_id_str: str) -> MessageID:
    """Safely handle message ID as string."""
    return MessageID(msg_id_str)


def safe_parse_message_id(msg_id_str: str) -> tuple[bytes, bytes]:
    """
    Safely parse message ID using ast.literal_eval with validation.
    :param msg_id_str: String representation of message ID
    :return: Tuple of (seqno, from_id) as bytes
    :raises ValueError: If parsing fails
    """
    try:
        parsed = ast.literal_eval(msg_id_str)
        if not isinstance(parsed, tuple) or len(parsed) != 2:
            raise ValueError("Invalid message ID format")

        seqno, from_id = parsed
        if not isinstance(seqno, bytes) or not isinstance(from_id, bytes):
            raise ValueError("Message ID components must be bytes")

        return (seqno, from_id)
    except (ValueError, SyntaxError) as e:
        raise ValueError(f"Invalid message ID format: {e}")
