"""
Connection state management for libp2p connections.

This module provides connection state tracking and timeline management
matching JavaScript libp2p behavior.

Reference: https://github.com/libp2p/js-libp2p/blob/main/packages/libp2p/src/connection-manager/index.ts
"""

from dataclasses import dataclass, field
import enum
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


class ConnectionStatus(enum.Enum):
    """
    Connection status states matching JS libp2p.

    Status values:
    - PENDING: Connection being established
    - OPEN: Connection established and active
    - CLOSING: Connection is closing
    - CLOSED: Connection is closed
    """

    PENDING = "pending"
    OPEN = "open"
    CLOSING = "closing"
    CLOSED = "closed"


@dataclass
class ConnectionTimeline:
    """
    Connection timeline tracking creation and closure times.

    Matches JS libp2p connection timeline structure.
    """

    open: float = field(default_factory=time.time)
    close: float | None = None

    def to_dict(self) -> dict[str, float | None]:
        """
        Convert timeline to dictionary.

        Returns
        -------
        dict[str, float | None]
            Dictionary with 'open' and optional 'close' timestamps

        """
        result: dict[str, float | None] = {"open": self.open}
        if self.close is not None:
            result["close"] = self.close
        return result


@dataclass
class ConnectionState:
    """
    Connection state tracking for libp2p connections.

    Tracks status and timeline information matching JS libp2p.
    """

    status: ConnectionStatus = ConnectionStatus.PENDING
    timeline: ConnectionTimeline = field(default_factory=ConnectionTimeline)

    def set_status(self, status: ConnectionStatus) -> None:
        """
        Set connection status and update timeline.

        Parameters
        ----------
        status : ConnectionStatus
            New connection status

        """
        self.status = status

        # Update timeline when status changes
        if status == ConnectionStatus.OPEN:
            self.timeline.open = time.time()
        elif status == ConnectionStatus.CLOSED:
            self.timeline.close = time.time()

    def to_dict(self) -> dict[str, Any]:
        """
        Convert connection state to dictionary.

        Returns
        -------
        dict[str, any]
            Dictionary representation of connection state

        """
        return {
            "status": self.status.value,
            "timeline": self.timeline.to_dict(),
        }
