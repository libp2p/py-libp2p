"""
Protocol buffer package for peer records.

Contains generated protobuf code for peer record and envelope definitions.
"""

# Import the classes to be accessible directly from the package
from .envelope_pb2 import (
    Envelope,
)
from .peer_record_pb2 import (
    PeerRecord,
)

__all__ = ["Envelope", "PeerRecord"]
