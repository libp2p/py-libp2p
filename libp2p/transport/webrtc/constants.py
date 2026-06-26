"""
WebRTC transport constants.

Protocol codes, message size limits, and data-channel ID allocation rules
per the libp2p WebRTC specification.

Spec: https://github.com/libp2p/specs/tree/master/webrtc
"""

from libp2p.custom_types import TProtocol

# ---------------------------------------------------------------------------
# Multiaddr protocol codes
# https://github.com/multiformats/multicodec/blob/master/table.csv
# ---------------------------------------------------------------------------
WEBRTC_DIRECT_PROTOCOL_CODE = 0x0118
WEBRTC_PROTOCOL_CODE = 0x0119
CERTHASH_PROTOCOL_CODE = 0x01D2

# ---------------------------------------------------------------------------
# Protocol IDs (used during multistream-select negotiation)
# ---------------------------------------------------------------------------
WEBRTC_SIGNALING_PROTOCOL_ID = TProtocol("/webrtc-signaling/0.0.1")

# ---------------------------------------------------------------------------
# Message size constraints (from spec §Message Framing)
# ---------------------------------------------------------------------------
# Hard ceiling for the full framed wire message: uvarint(proto_len) + proto_len.
MAX_MESSAGE_SIZE = 16_384
# Maximum payload bytes per Message(message=...) frame, chosen so the worst-case
# wire encoding stays within MAX_MESSAGE_SIZE:
#   outer uvarint (2 bytes) + proto field tag (1) + inner uvarint (2) + N <= 16384
# => N <= 16379.  Conservative round-down leaves a few bytes of safety margin
# for future small additions to the Message schema.
MAX_PAYLOAD_SIZE = 16_368
# Spec-recommended payload, avoids IP fragmentation at the IPv6 minimum MTU.
RECOMMENDED_PAYLOAD_SIZE = 1_200

# ---------------------------------------------------------------------------
# Data-channel ID allocation (from spec §Multiplexing)
# ---------------------------------------------------------------------------
NOISE_HANDSHAKE_CHANNEL_ID = 0  # Reserved for Noise XX handshake
OUTBOUND_STREAM_START_ID = 2  # Even IDs for outbound streams
INBOUND_STREAM_START_ID = 1  # Odd IDs for inbound streams

# ---------------------------------------------------------------------------
# Noise handshake prologue prefix (from spec §Security)
# ---------------------------------------------------------------------------
NOISE_PROLOGUE_PREFIX = b"libp2p-webrtc-noise:"

# ---------------------------------------------------------------------------
# ICE / DTLS configuration defaults
# ---------------------------------------------------------------------------
ICE_DISCONNECTION_TIMEOUT = 20  # seconds
ICE_FAILURE_TIMEOUT = 30  # seconds
ICE_KEEPALIVE_INTERVAL = 15  # seconds

# ---------------------------------------------------------------------------
# Connection limits (matching go-libp2p defaults)
# ---------------------------------------------------------------------------
MAX_IN_FLIGHT_CONNECTIONS = 128
ACCEPT_QUEUE_SIZE = 256
MAX_DATA_CHANNELS = 65_535  # Per WebRTC spec
