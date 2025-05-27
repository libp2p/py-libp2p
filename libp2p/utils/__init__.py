"""Utility functions for libp2p."""

from libp2p.utils.varint import (
    decode_uvarint_from_stream,
    encode_delim,
    encode_uvarint,
    encode_varint_prefixed,
    read_delim,
    read_varint_prefixed_bytes,
)
from libp2p.utils.version import (
    get_agent_version,
)

__all__ = [
    "decode_uvarint_from_stream",
    "encode_delim",
    "encode_uvarint",
    "encode_varint_prefixed",
    "get_agent_version",
    "read_delim",
    "read_varint_prefixed_bytes",
]
