"""
WebRTC transport configuration.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .certificate import WebRTCCertificate
from .constants import (
    ACCEPT_QUEUE_SIZE,
    ICE_DISCONNECTION_TIMEOUT,
    ICE_FAILURE_TIMEOUT,
    ICE_KEEPALIVE_INTERVAL,
    MAX_IN_FLIGHT_CONNECTIONS,
    MAX_MESSAGE_SIZE,
)


@dataclass
class WebRTCTransportConfig:
    """
    Configuration for the WebRTC transport.

    Sensible defaults match go-libp2p.  Override for testing or
    constrained environments.
    """

    # ------------------------------------------------------------------
    # Certificate (auto-generated if None)
    # ------------------------------------------------------------------
    certificate: WebRTCCertificate | None = None

    # ------------------------------------------------------------------
    # ICE timeouts (seconds)
    # ------------------------------------------------------------------
    ice_disconnection_timeout: float = float(ICE_DISCONNECTION_TIMEOUT)
    ice_failure_timeout: float = float(ICE_FAILURE_TIMEOUT)
    ice_keepalive_interval: float = float(ICE_KEEPALIVE_INTERVAL)

    # ------------------------------------------------------------------
    # Connection timeouts (seconds)
    # ------------------------------------------------------------------
    handshake_timeout: float = 30.0
    stream_open_timeout: float = 10.0
    stream_accept_timeout: float = 10.0

    # ------------------------------------------------------------------
    # Concurrency limits
    # ------------------------------------------------------------------
    max_in_flight_connections: int = MAX_IN_FLIGHT_CONNECTIONS
    accept_queue_size: int = ACCEPT_QUEUE_SIZE
    max_concurrent_streams: int = 256

    # ------------------------------------------------------------------
    # Message size
    # ------------------------------------------------------------------
    max_message_size: int = MAX_MESSAGE_SIZE

    # ------------------------------------------------------------------
    # STUN / TURN servers (for ICE candidate gathering)
    # ------------------------------------------------------------------
    # Only used by the experimental HTTP ``/sdp`` harness. The WebRTC-Direct
    # spec path never configures STUN/TURN: it dials a known public address
    # and the listener infers the offer from the first STUN packet.
    ice_servers: list[str] = field(
        default_factory=lambda: ["stun:stun.l.google.com:19302"]
    )

    # ------------------------------------------------------------------
    # WebRTC-Direct signaling
    # ------------------------------------------------------------------
    # The spec path needs no signaling: the listener infers the dialer's
    # offer from its first STUN packet (one shared UDP port, v1/v2 ufrag
    # dispatch). The HTTP ``POST /sdp`` harness predates that and is kept
    # only as an experimental py<->py debugging aid: when enabled the
    # listener also serves it on TCP (same port number) and our dialer
    # uses it instead of the STUN path. Not interoperable with other
    # implementations.
    enable_sdp_http_harness: bool = False
    # WebRTC-Direct version our *dialer* speaks: 1 munges the local ICE
    # credentials (ufrag == pwd); 2 keeps them and encodes our pwd in the
    # synthetic answer's ufrag (libp2p/specs#715). Default 1 while #715 is
    # unmerged. The listener accepts both regardless.
    webrtc_direct_dial_version: int = 1

    def get_or_generate_certificate(self) -> WebRTCCertificate:
        """
        Return the configured certificate or generate a new one.

        Prefers aiortc-native generation when available so the resulting
        ``RTCCertificate`` can be passed directly to
        ``RTCPeerConnection(certificates=[...])``.  Falls back to pure
        ``cryptography`` generation when aiortc is not installed.
        """
        if self.certificate is None:
            try:
                self.certificate = WebRTCCertificate.from_aiortc()
            except ImportError:
                self.certificate = WebRTCCertificate.generate()
        return self.certificate
