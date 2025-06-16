"""
Protocol buffer wrapper classes for Circuit Relay v2.

This module provides wrapper classes for protocol buffer generated objects
to make them easier to work with in type-checked code.
"""

from enum import (
    IntEnum,
)
from typing import (
    Any,
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
    INTERNAL_ERROR = 500


def create_status(code: int = StatusCode.OK, message: str = "") -> Any:
    """
    Create a protocol buffer Status object.

    Parameters
    ----------
    code : int
        The status code
    message : str
        The status message

    Returns
    -------
    Any
        The protocol buffer Status object

    """
    # Create status object
    pb_obj = PbStatus()

    # Convert the integer status code to the protobuf enum value type
    pb_obj.code = PbStatus.Code.ValueType(code)
    pb_obj.message = message

    return pb_obj
