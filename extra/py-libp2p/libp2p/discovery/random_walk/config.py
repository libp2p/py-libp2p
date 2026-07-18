from typing import Final

# Timing constants (matching go-libp2p)
PEER_PING_TIMEOUT: Final[float] = 10.0  # seconds
REFRESH_QUERY_TIMEOUT: Final[float] = 60.0  # seconds
REFRESH_INTERVAL: Final[float] = 300.0  # 5 minutes
SUCCESSFUL_OUTBOUND_QUERY_GRACE_PERIOD: Final[float] = 60.0  # 1 minute

# Routing table thresholds
MIN_RT_REFRESH_THRESHOLD: Final[int] = 4  # Minimum peers before triggering refresh
MAX_N_BOOTSTRAPPERS: Final[int] = 2  # Maximum bootstrap peers to try

# Random walk specific
RANDOM_WALK_CONCURRENCY: Final[int] = 3  # Number of concurrent random walks
RANDOM_WALK_ENABLED: Final[bool] = True  # Enable automatic random walks
RANDOM_WALK_RT_THRESHOLD: Final[int] = 20  # RT size threshold for peerstore fallback
