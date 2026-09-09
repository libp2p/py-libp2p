"""WebTransport transport configuration."""

from __future__ import annotations

from dataclasses import dataclass

from .cert_manager import WebTransportCertManager

WELL_KNOWN_PATH = "/.well-known/libp2p-webtransport?type=noise"
ALPN_H3 = "h3"
# Required for ENABLE_WEBTRANSPORT (needs H3_DATAGRAM).
DEFAULT_MAX_DATAGRAM_FRAME_SIZE = 65536


@dataclass
class WebTransportConfig:
    """Configuration for the WebTransport transport."""

    cert_manager: WebTransportCertManager | None = None
    handshake_timeout: float = 30.0
    idle_timeout: float = 60.0
    accept_queue_size: int = 32
    max_concurrent_streams: int = 256
    max_datagram_frame_size: int = DEFAULT_MAX_DATAGRAM_FRAME_SIZE
    well_known_path: str = WELL_KNOWN_PATH

    def get_or_create_cert_manager(self) -> WebTransportCertManager:
        if self.cert_manager is None:
            self.cert_manager = WebTransportCertManager()
        return self.cert_manager
