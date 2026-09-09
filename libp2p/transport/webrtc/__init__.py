"""
WebRTC transport for libp2p.

Provides two transport variants per the libp2p WebRTC specification:

- **WebRTC Direct** (``/webrtc-direct``): Server-to-browser or server-to-server
  connections where the server publishes its certificate hash in the multiaddr.
  No relay or signaling server is required.

  There are two ways to signal a WebRTC-Direct connection, and they are not
  interchangeable:

  * **STUN listener (spec path, default).** Inbound dials hit one shared UDP
    port; the listener infers the SDP offer from the first STUN packet and
    answers over a muxed ICE agent. Outbound dials synthesise an ICE-Lite
    answer from the multiaddr with no public STUN servers. This is the only
    path that interoperates with go-libp2p / js-libp2p / browsers.
  * **HTTP ``POST /sdp`` harness (dev only).** Opt-in via
    ``WebRTCTransportConfig(enable_sdp_http_harness=True)``; a minimal HTTP
    signalling server for **py↔py debugging only** — it is *not* interoperable
    with other libp2p implementations. Leave it off in production.

  **Dial version — v1 vs v2 (libp2p/specs#715).** The listener always accepts
  both. The dialer picks with ``WebRTCTransportConfig(webrtc_direct_dial_version=
  1|2)``:

  * **v1 (default today):** the migration path. Encodes the client password by
    munging the ICE ufrag/pwd; kept the default while specs#715 is unmerged so
    py↔py and py↔go keep working against v1 peers.
  * **v2 (recommended):** the specs#715 flow — no SDP munging
    (``libp2p+webrtc+v2/<client_pwd>``). Prefer it for new deployments, and it
    is what **browser dialling requires** once ``NoSdpMangleUfrag`` support is
    widespread. Switch the default to v2 once specs#715 lands.

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
