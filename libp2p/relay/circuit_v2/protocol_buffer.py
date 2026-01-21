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

from .pb.circuit_pb2 import Status as PbStatus


# Define Status codes as an Enum for better type safety and organization
class StatusCode(IntEnum):
    OK = 0
    RESERVATION_REFUSED = 100
    RESOURCE_LIMIT_EXCEEDED = 101
    PERMISSION_DENIED = 102
    CONNECTION_FAILED = 200
    DIAL_REFUSED = 201
    STOP_FAILED = 300
    MALFORMED_MESSAGE = 400


def create_status(code: int = StatusCode.OK, message: str = "") -> PbStatus:
    """
    Create a protocol buffer Status object.

    Parameters
    ----------
    code : int
        The status code. Can be a StatusCode enum value or an integer.
    message : str
        The status message

    Returns
    -------
    PbStatus
        The protocol buffer Status object

    """
    pb_obj = PbStatus()

    # Convert the status code (int or StatusCode enum) to the protobuf enum value type.
    # The code field expects PbStatus.Code.ValueType (a NewType wrapper around int).
    # At runtime, protobuf accepts int directly, but type checker requires ValueType.
    pb_obj.code = cast(PbStatus.Code.ValueType, int(code))  # type: ignore[assignment,attr-defined]
    pb_obj.message = message

    return pb_obj
