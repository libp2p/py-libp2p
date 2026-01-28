"""
Perf protocol interfaces and types.

The perf protocol is used to measure transfer performance within and across
libp2p implementations.

Spec: https://github.com/libp2p/specs/blob/master/perf/perf.md
"""

from abc import ABC, abstractmethod
from typing import (
    TYPE_CHECKING,
    AsyncIterator,
    Literal,
    Optional,
    TypedDict,
)

if TYPE_CHECKING:
    from multiaddr import Multiaddr

    from libp2p.abc import IHost


# ------------------------------- Types -------------------------------


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


class PerfOptions(TypedDict, total=False):
    """Options for a performance measurement run."""

    reuse_existing_connection: bool  # Default: False


class PerfComponents(TypedDict):
    """Components required by the perf service."""

    host: "IHost"


# ------------------------------- Interface -------------------------------


class IPerf(ABC):
    """Interface for the perf protocol service."""

    @abstractmethod
    async def start(self) -> None:
        """Start the perf service and register the protocol handler."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Stop the perf service and unregister the protocol handler."""
        ...

    @abstractmethod
    def is_started(self) -> bool:
        """Check if the service is currently running."""
        ...

    @abstractmethod
    def measure_performance(
        self,
        multiaddr: "Multiaddr",
        send_bytes: int,
        recv_bytes: int,
        options: Optional[PerfOptions] = None,
    ) -> AsyncIterator[PerfOutput]:
        """
        Measure transfer performance to a remote peer.

        Parameters
        ----------
        multiaddr : Multiaddr
            The address of the remote peer to test against.
        send_bytes : int
            Number of bytes to upload to the remote peer.
        recv_bytes : int
            Number of bytes to request the remote peer to send back.
        options : PerfOptions, optional
            Options for the performance run.

        Yields
        ------
        PerfOutput
            Progress reports during the transfer, with a final summary at the end.

        """
        ...
