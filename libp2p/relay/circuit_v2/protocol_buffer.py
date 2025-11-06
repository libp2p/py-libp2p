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
        The status code
    message : str
        The status message

    Returns
    -------
    PbStatus
        The protocol buffer Status object

    """
    pb_obj = PbStatus()
    pb_obj.code = cast(Any, int(code))
    pb_obj.message = message

    return pb_obj
