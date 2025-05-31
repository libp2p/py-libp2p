"""
Protocol buffer wrapper classes for Circuit Relay v2.

This module provides wrapper classes for protocol buffer generated objects
to make them easier to work with in type-checked code.
"""

from typing import (
    Any,
)

# Define constants for Status codes to use in code
OK = 0
RESERVATION_REFUSED = 100
RESOURCE_LIMIT_EXCEEDED = 101
PERMISSION_DENIED = 102
CONNECTION_FAILED = 200
DIAL_REFUSED = 201
STOP_FAILED = 300
MALFORMED_MESSAGE = 400
INTERNAL_ERROR = 500


def create_status(code: int = OK, message: str = "") -> Any:
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
    # Import here to avoid circular imports
    from .pb.circuit_pb2 import Status as PbStatus

    # Create status object
    pb_obj = PbStatus()

    # Direct attribute access - we know these exist at runtime
    # but mypy can't see them in the stub files
    pb_obj.code = code  # type: ignore
    pb_obj.message = message  # type: ignore

    return pb_obj
