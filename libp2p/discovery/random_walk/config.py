from typing import Final

# Timing constants
PEER_PING_TIMEOUT: Final[float] = 10.0  # seconds
REFRESH_QUERY_TIMEOUT: Final[float] = 60.0  # seconds
REFRESH_INTERVAL: Final[float] = 120.0  # 2 minutes for steady discovery
SUCCESSFUL_OUTBOUND_QUERY_GRACE_PERIOD: Final[float] = 60.0  # 1 minute
# Wall-clock cap for one full random-walk batch inside _do_refresh().
REFRESH_TOTAL_TIMEOUT: Final[float] = 120.0  # seconds

# Routing table thresholds
MAX_N_BOOTSTRAPPERS: Final[int] = 2  # Maximum bootstrap peers to try

# Random walk specific
RANDOM_WALK_CONCURRENCY: Final[int] = 3  # Safe concurrency for Python async event loop
RANDOM_WALK_ENABLED: Final[bool] = True
RANDOM_WALK_RT_THRESHOLD: Final[int] = 20  # RT size threshold for peerstore fallback
