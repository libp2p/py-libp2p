from datetime import (
    datetime,
    timedelta,
)
import logging
from typing import (
    Optional,
)

logger = logging.getLogger("libp2p.transport.quic.metrics")


class QuicMetrics:
    """Metrics collection for QUIC connections."""

    def __init__(self) -> None:
        self.bytes_sent = 0
        self.bytes_received = 0
        self.streams_opened = 0
        self.streams_closed = 0
        self.connection_start_time = datetime.now()
        self.handshake_duration: Optional[timedelta] = None
        self.errors_count = 0

    def log_metrics(self) -> None:
        """Log current metrics."""
        logger.info(
            "quic_metrics: bytes_sent=%d, bytes_received=%d, streams_opened=%d, "
            "streams_closed=%d, uptime=%s, handshake_duration=%s, errors_count=%d",
            self.bytes_sent,
            self.bytes_received,
            self.streams_opened,
            self.streams_closed,
            str(datetime.now() - self.connection_start_time),
            str(self.handshake_duration) if self.handshake_duration else "None",
            self.errors_count,
        )
