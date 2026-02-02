"""
Perf protocol for measuring transfer performance.

This module implements the libp2p perf protocol as specified in:
https://github.com/libp2p/specs/blob/master/perf/perf.md
"""

from .constants import (
    MAX_INBOUND_STREAMS,
    MAX_OUTBOUND_STREAMS,
    PROTOCOL_NAME,
    RUN_ON_LIMITED_CONNECTION,
    WRITE_BLOCK_SIZE,
)
from .types import (
    PerfComponents,
    PerfInit,
    PerfOptions,
    PerfOutput,
)
from libp2p.abc import IPerf
from .perf_service import PerfService

__all__ = [
    # Constants
    "PROTOCOL_NAME",
    "WRITE_BLOCK_SIZE",
    "MAX_INBOUND_STREAMS",
    "MAX_OUTBOUND_STREAMS",
    "RUN_ON_LIMITED_CONNECTION",
    # Types
    "PerfOutput",
    "PerfInit",
    "PerfOptions",
    "PerfComponents",
    # Interface
    "IPerf",
    # Implementation
    "PerfService",
]
