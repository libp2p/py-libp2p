"""
Protocol buffer helpers for Circuit Relay v2.

``Status`` is a top-level protobuf enum (rust-libp2p / spec), not a submessage.
"""

from enum import IntEnum


class StatusCode(IntEnum):
    """Same numeric values as ``circuit_pb2.Status`` (spec / rust-libp2p)."""

    UNUSED = 0
    OK = 100
    RESERVATION_REFUSED = 200
    RESOURCE_LIMIT_EXCEEDED = 201
    PERMISSION_DENIED = 202
    CONNECTION_FAILED = 203
    NO_RESERVATION = 204
    MALFORMED_MESSAGE = 400
    UNEXPECTED_MESSAGE = 401


def pb_status_value(code: int | StatusCode) -> int:
    return int(code)
