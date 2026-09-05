"""
WebRTC transport for libp2p.

Provides two transport variants per the libp2p WebRTC specification:

- **WebRTC Direct** (``/webrtc-direct``): Server-to-browser or server-to-server
  connections where the server publishes its certificate hash in the multiaddr.
  No relay or signaling server is required. The default path uses inbound STUN
  on a shared UDP port (offer inferred from the first packet) and outbound
  dials that synthesise an ICE-Lite answer without public STUN servers. The
  listener accepts both the v1 (munging) and v2 (libp2p/specs#715) flows; the
  dialer speaks v1 by default (``webrtc_direct_dial_version=2`` opts in). An
  experimental HTTP ``POST /sdp`` harness (``WebRTCTransportConfig(
  enable_sdp_http_harness=True)``) is available for py↔py debugging only.

- **WebRTC** (``/webrtc``): Private-to-private connections where both peers are
  behind NAT.  Uses Circuit Relay v2 for signaling, then upgrades to a direct
  WebRTC data-channel connection.

Both variants use Noise XX over data-channel 0 for authentication and rely on
WebRTC data channels for native stream multiplexing (no Yamux/Mplex needed).

Spec: https://github.com/libp2p/specs/tree/master/webrtc
"""

from libp2p.transport.webrtc.certificate import (
    WebRTCCertificate,
)
from libp2p.transport.webrtc.constants import (
    ACCEPT_QUEUE_SIZE,
    CERTHASH_PROTOCOL_CODE,
    ICE_DISCONNECTION_TIMEOUT,
    ICE_FAILURE_TIMEOUT,
    ICE_KEEPALIVE_INTERVAL,
    INBOUND_STREAM_START_ID,
    MAX_DATA_CHANNELS,
    MAX_IN_FLIGHT_CONNECTIONS,
    MAX_MESSAGE_SIZE,
    NOISE_HANDSHAKE_CHANNEL_ID,
    NOISE_PROLOGUE_PREFIX,
    OUTBOUND_STREAM_START_ID,
    RECOMMENDED_PAYLOAD_SIZE,
    WEBRTC_DIRECT_PROTOCOL_CODE,
    WEBRTC_PROTOCOL_CODE,
    WEBRTC_SIGNALING_PROTOCOL_ID,
)
from libp2p.transport.webrtc.exceptions import (
    WebRTCCertificateError,
    WebRTCConnectionError,
    WebRTCError,
    WebRTCHandshakeError,
    WebRTCMultiaddrError,
    WebRTCSignalingError,
    WebRTCStreamError,
)

__all__ = [
    # Constants
    "ACCEPT_QUEUE_SIZE",
    "CERTHASH_PROTOCOL_CODE",
    "ICE_DISCONNECTION_TIMEOUT",
    "ICE_FAILURE_TIMEOUT",
    "ICE_KEEPALIVE_INTERVAL",
    "INBOUND_STREAM_START_ID",
    "MAX_DATA_CHANNELS",
    "MAX_IN_FLIGHT_CONNECTIONS",
    "MAX_MESSAGE_SIZE",
    "NOISE_HANDSHAKE_CHANNEL_ID",
    "NOISE_PROLOGUE_PREFIX",
    "OUTBOUND_STREAM_START_ID",
    "RECOMMENDED_PAYLOAD_SIZE",
    "WEBRTC_DIRECT_PROTOCOL_CODE",
    "WEBRTC_PROTOCOL_CODE",
    "WEBRTC_SIGNALING_PROTOCOL_ID",
    # Certificate
    "WebRTCCertificate",
    # Exceptions
    "WebRTCCertificateError",
    "WebRTCConnectionError",
    "WebRTCError",
    "WebRTCHandshakeError",
    "WebRTCMultiaddrError",
    "WebRTCSignalingError",
    "WebRTCStreamError",
]
