from libp2p.custom_types import TProtocol

# Default ICE servers for NAT traversal
DEFAULT_ICE_SERVERS = [
    {"urls": "stun:stun.l.google.com:19302"},
    {"urls": "stun:global.stun.twilio.com:3478"},
    {"urls": "stun:stun.cloudflare.com:3478"},
    {"urls": "stun:stun.services.mozilla.com:3478"},
]

# WebRTC signaling protocol
SIGNALING_PROTOCOL = TProtocol("/webrtc-signaling/0.0.1")

# WebRTC muxer protocol
MUXER_PROTOCOL = "/webrtc"

# Multicodec codes
CODEC_WEBRTC = 0x0119  # WebRTC protocol code
CODEC_WEBRTC_DIRECT = 0x0118  # WebRTC-Direct protocol code
CODEC_CERTHASH = 0x01D2  # Certificate hash code

# Multiaddr protocol codes
PROTOCOL_WEBRTC = "webrtc"
PROTOCOL_WEBRTC_DIRECT = "webrtc-direct"
PROTOCOL_CERTHASH = "certhash"

# Data channel configuration
MAX_BUFFERED_AMOUNT = (
    256 * 1024
)  # 256KB (reduced from 2MB to prevent backpressure deadlocks)
BUFFERED_AMOUNT_LOW_TIMEOUT = 30.0  # 30 seconds (float for trio.move_on_after)
MAX_MESSAGE_SIZE = 16 * 1024  # 16KB (compatible with go-libp2p and rust-libp2p)

# Stream handling timeouts (all in seconds as floats for trio.move_on_after)
FIN_ACK_TIMEOUT = 5.0  # 5 seconds
OPEN_TIMEOUT = 5.0  # 5 seconds
DATA_CHANNEL_DRAIN_TIMEOUT = 30.0  # 30 seconds
DEFAULT_READ_TIMEOUT = 30.0  # 30 seconds
# WebRTC-Direct specific constants
UFRAG_PREFIX = "libp2p+webrtc+v1/"
UFRAG_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890"

# Certificate management
DEFAULT_CERTIFICATE_DATASTORE_KEY = "/libp2p/webrtc-direct/certificate"
DEFAULT_CERTIFICATE_PRIVATE_KEY_NAME = "webrtc-direct-certificate-private-key"
DEFAULT_CERTIFICATE_PRIVATE_KEY_TYPE = "ECDSA"
DEFAULT_CERTIFICATE_LIFESPAN = 1_209_600_000  # 14 days in milliseconds
DEFAULT_CERTIFICATE_RENEWAL_THRESHOLD = 86_400_000  # 1 day in milliseconds

# Protocol overhead calculations
PROTOBUF_OVERHEAD = 5  # Estimated protobuf message overhead
MESSAGE_OVERHEAD = PROTOBUF_OVERHEAD + 4  # Include length prefix

# Connection states
WEBRTC_CONNECTION_STATES = {
    "new": "new",
    "connecting": "connecting",
    "connected": "connected",
    "disconnected": "disconnected",
    "failed": "failed",
    "closed": "closed",
}

WEBRTC_PROTOCOL = "webrtc"

# Data channel states
DATA_CHANNEL_STATES = {
    "connecting": "connecting",
    "open": "open",
    "closing": "closing",
    "closed": "closed",
}


# Error codes
class WebRTCError(Exception):
    """Base WebRTC transport error"""

    pass


class SDPHandshakeError(WebRTCError):
    """SDP handshake failed"""

    pass


class ConnectionStateError(WebRTCError):
    """Invalid connection state"""

    pass


class CertificateError(WebRTCError):
    """Certificate related error"""

    pass


class STUNError(WebRTCError):
    """STUN protocol error"""

    pass


# WebRTC transport types
TRANSPORT_TYPE_WEBRTC = "webrtc"
TRANSPORT_TYPE_WEBRTC_DIRECT = "webrtc-direct"

# Default timeouts and retries
DEFAULT_DIAL_TIMEOUT = 60.0  # seconds
DEFAULT_LISTEN_TIMEOUT = 60.0  # seconds
DEFAULT_HANDSHAKE_TIMEOUT = 40.0  # seconds
DEFAULT_ICE_GATHERING_TIMEOUT = 10.0  # seconds
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_DELAY = 1.0  # seconds
MUXER_NEGOTIATE_TIMEOUT = 45.0  # seconds - dedicated muxer negotiation timeout
MUXER_READ_TIMEOUT = 30.0  # seconds - per-read timeout during muxer negotiation

# Buffer sizes
DEFAULT_STREAM_BUFFER_SIZE = 64 * 1024  # 64KB
DEFAULT_CHANNEL_BUFFER_SIZE = 256 * 1024  # 256KB

# Logging levels
LOG_LEVEL_TRACE = "TRACE"
LOG_LEVEL_DEBUG = "DEBUG"
LOG_LEVEL_INFO = "INFO"
LOG_LEVEL_WARNING = "WARNING"
LOG_LEVEL_ERROR = "ERROR"

# Multiaddr protocol registration
MULTIADDR_PROTOCOLS = {
    PROTOCOL_WEBRTC: {
        "code": CODEC_WEBRTC,
        "size": 0,
        "name": "webrtc",
        "resolvable": False,
    },
    PROTOCOL_WEBRTC_DIRECT: {
        "code": CODEC_WEBRTC_DIRECT,
        "size": 0,
        "name": "webrtc-direct",
        "resolvable": False,
    },
    PROTOCOL_CERTHASH: {
        "code": CODEC_CERTHASH,
        "size": 0,
        "name": "certhash",
        "resolvable": False,
    },
}
