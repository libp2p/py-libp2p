from typing import Final

# Timing constants
# NOTE: go-libp2p defaults (CONCURRENCY=10, INTERVAL=60s) were designed for
# multi-threaded Go. Python is single-threaded — 10 concurrent random walks
# each dialing 20+ peers = 200 QUIC dials/minute → 100% CPU.
# Reduced to safe levels for a Python single-threaded event loop.
PEER_PING_TIMEOUT: Final[float] = 10.0  # seconds
REFRESH_QUERY_TIMEOUT: Final[float] = 60.0  # seconds
REFRESH_INTERVAL: Final[float] = 600.0  # 10 minutes (was 300s → halves burst frequency)
SUCCESSFUL_OUTBOUND_QUERY_GRACE_PERIOD: Final[float] = 60.0  # 1 minute
# Wall-clock cap for one full random-walk batch inside _do_refresh().
REFRESH_TOTAL_TIMEOUT: Final[float] = 30.0  # seconds

# Routing table thresholds
MAX_N_BOOTSTRAPPERS: Final[int] = 2  # Maximum bootstrap peers to try

# Random walk specific
RANDOM_WALK_CONCURRENCY: Final[int] = 10  # Standard libp2p spec concurrency
RANDOM_WALK_ENABLED: Final[bool] = True
RANDOM_WALK_RT_THRESHOLD: Final[int] = 20  # RT size threshold for peerstore fallback
