"""
Protocol buffer wrapper classes for Circuit Relay v2.

This module provides wrapper classes for protocol buffer generated objects
to make them easier to work with in type-checked code.
"""

from enum import (
    IntEnum,
)
from typing import (
    cast,
)

from .pb.circuit_pb2 import (
    Status,
)


# Status codes for circuit relay v2, mirroring the canonical protobuf
# definition. Note this is a plain enum: on the wire, HopMessage.status and
# StopMessage.status carry one of these values directly.
class StatusCode(IntEnum):
    UNUSED = 0
    OK = 100
    RESERVATION_REFUSED = 200
    RESOURCE_LIMIT_EXCEEDED = 201
    PERMISSION_DENIED = 202
    CONNECTION_FAILED = 203
    NO_RESERVATION = 204
    MALFORMED_MESSAGE = 400
    UNEXPECTED_MESSAGE = 401


def to_proto_status(code: StatusCode) -> Status:
    """
    Convert a ``StatusCode`` to the generated protobuf ``Status`` enum.

    The generated ``EnumTypeWrapper`` is not callable, so the wire value
    (identical integers) is passed through with a cast.
    """
    return cast(Status, int(code))


def create_status(code: int = StatusCode.OK) -> StatusCode:
    """
    Create a protocol buffer Status value.

    Parameters
    ----------
    code : int
        The status code. Can be a StatusCode enum value or an integer.

    Returns
    -------
    StatusCode
        The status enum value for assignment to HopMessage.status or
        StopMessage.status.

    """
    return StatusCode(int(code))
