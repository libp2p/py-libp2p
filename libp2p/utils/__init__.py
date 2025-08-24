"""Utility functions for libp2p."""

from libp2p.utils.varint import (
    decode_uvarint_from_stream,
    encode_delim,
    encode_uvarint,
    encode_varint_prefixed,
    read_delim,
    read_varint_prefixed_bytes,
    decode_varint_from_bytes,
    decode_varint_with_size,
    read_length_prefixed_protobuf,
)
from libp2p.utils.version import (
    get_agent_version,
)

from libp2p.utils.address_validation import (
    get_available_interfaces,
    get_optimal_binding_address,
    expand_wildcard_address,
    find_free_port,
)

__all__ = [
    "decode_uvarint_from_stream",
    "encode_delim",
    "encode_uvarint",
    "encode_varint_prefixed",
    "get_agent_version",
    "read_delim",
    "read_varint_prefixed_bytes",
    "decode_varint_from_bytes",
    "decode_varint_with_size",
    "read_length_prefixed_protobuf",
    "get_available_interfaces",
    "get_optimal_binding_address",
    "expand_wildcard_address",
    "find_free_port",
]
