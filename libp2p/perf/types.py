"""
Perf protocol types.

Spec: https://github.com/libp2p/specs/blob/master/perf/perf.md
"""

from typing import (
    TYPE_CHECKING,
    Literal,
    TypedDict,
)

if TYPE_CHECKING:
    from libp2p.abc import IHost


class PerfOutput(TypedDict):
    """Output data from a performance measurement."""

    type: Literal["connection", "stream", "intermediary", "final"]
    time_seconds: float
    upload_bytes: int
    download_bytes: int


class PerfInit(TypedDict, total=False):
    """Initialization options for the perf service."""

    protocol_name: str
    max_inbound_streams: int
    max_outbound_streams: int
    run_on_limited_connection: bool
    write_block_size: int  # Default: 65536 (64KB)


class PerfComponents(TypedDict):
    """Components required by the perf service."""

    host: "IHost"
