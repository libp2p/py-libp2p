from dataclasses import dataclass


@dataclass
class RetryConfig:
    """
    Configuration for retry logic with exponential backoff.

    This configuration controls how connection attempts are retried when they fail.
    The retry mechanism uses exponential backoff with jitter to prevent thundering
    herd problems in distributed systems.

    Attributes:
        max_retries: Maximum number of retry attempts before giving up.
                     Default: 3 attempts
        initial_delay: Initial delay in seconds before the first retry.
                      Default: 0.1 seconds (100ms)
        max_delay: Maximum delay cap in seconds to prevent excessive wait times.
                  Default: 30.0 seconds
        backoff_multiplier: Multiplier for exponential backoff (each retry multiplies
                           the delay by this factor). Default: 2.0 (doubles each time)
        jitter_factor: Random jitter factor (0.0-1.0) to add randomness to delays
                      and prevent synchronized retries. Default: 0.1 (10% jitter)

    """

    max_retries: int = 3
    initial_delay: float = 0.1
    max_delay: float = 30.0
    backoff_multiplier: float = 2.0
    jitter_factor: float = 0.1


@dataclass
class ConnectionConfig:
    """
    Configuration for multi-connection support with health monitoring.

    This configuration controls how multiple connections per peer are managed,
    including connection limits, timeouts, load balancing strategies, and
    connection health monitoring capabilities.

    Attributes:
        max_connections_per_peer: Maximum number of connections allowed to a single
                                 peer. Default: 3 connections
        connection_timeout: Timeout in seconds for establishing new connections.
                           Default: 30.0 seconds
        load_balancing_strategy: Strategy for distributing streams across connections.
                                Options: "round_robin", "least_loaded",
                                "health_based", "latency_based"
        enable_health_monitoring: Enable/disable connection health monitoring.
                                 Default: False
        health_check_interval: Interval between health checks in seconds.
                              Default: 60.0
        ping_timeout: Timeout for ping operations in seconds. Default: 5.0
        min_health_threshold: Minimum health score (0.0-1.0) for connections.
                             Default: 0.3
        min_connections_per_peer: Minimum connections to maintain per peer.
                                 Default: 1
        latency_weight: Weight for latency in health scoring. Default: 0.4
        success_rate_weight: Weight for success rate in health scoring. Default: 0.4
        stability_weight: Weight for stability in health scoring. Default: 0.2
        max_ping_latency: Maximum acceptable ping latency in milliseconds.
                         Default: 1000.0
        min_ping_success_rate: Minimum acceptable ping success rate. Default: 0.7
        max_failed_streams: Maximum failed streams before connection replacement.
                           Default: 5

    """

    max_connections_per_peer: int = 3
    connection_timeout: float = 30.0
    load_balancing_strategy: str = "round_robin"  # Also: "least_loaded",
    # "health_based", "latency_based"

    # Health monitoring configuration
    enable_health_monitoring: bool = False
    # Delay before the first health check runs to avoid interfering with
    # connection establishment (seconds)
    health_initial_delay: float = 60.0
    # Skip health checks for very new connections during this warmup window
    health_warmup_window: float = 5.0
    health_check_interval: float = 60.0  # seconds
    ping_timeout: float = 5.0  # seconds
    min_health_threshold: float = 0.3  # 0.0 to 1.0
    min_connections_per_peer: int = 1

    # Health scoring weights
    latency_weight: float = 0.4
    success_rate_weight: float = 0.4
    stability_weight: float = 0.2

    # Connection replacement thresholds
    max_ping_latency: float = 1000.0  # milliseconds
    min_ping_success_rate: float = 0.7  # 70%
    max_failed_streams: int = 5
    # Require N consecutive unhealthy evaluations before replacement
    unhealthy_grace_period: int = 3
    # Health score threshold below which a connection is considered critically
    # unhealthy and can be replaced even at minimum connections
    critical_health_threshold: float = 0.1  # 0.0 to 1.0

    def __post_init__(self) -> None:
        """Validate configuration after initialization."""
        valid_strategies = [
            "round_robin",
            "least_loaded",
            "health_based",
            "latency_based",
        ]
        if self.load_balancing_strategy not in valid_strategies:
            raise ValueError(
                f"Load balancing strategy must be one of: {valid_strategies}"
            )

        if self.max_connections_per_peer < 1:
            raise ValueError("Max connection per peer should be atleast 1")

        if self.connection_timeout < 0:
            raise ValueError("Connection timeout should be positive")

        # Health monitoring validation
        if self.enable_health_monitoring:
            if self.health_check_interval <= 0:
                raise ValueError("Health check interval must be positive")
            if self.ping_timeout <= 0:
                raise ValueError("Ping timeout must be positive")
            if not 0.0 <= self.min_health_threshold <= 1.0:
                raise ValueError("Min health threshold must be between 0.0 and 1.0")
            if self.min_connections_per_peer < 1:
                raise ValueError("Min connections per peer must be at least 1")
            if not 0.0 <= self.latency_weight <= 1.0:
                raise ValueError("Latency weight must be between 0.0 and 1.0")
            if not 0.0 <= self.success_rate_weight <= 1.0:
                raise ValueError("Success rate weight must be between 0.0 and 1.0")
            if not 0.0 <= self.stability_weight <= 1.0:
                raise ValueError("Stability weight must be between 0.0 and 1.0")
            if self.max_ping_latency <= 0:
                raise ValueError("Max ping latency must be positive")
            if not 0.0 <= self.min_ping_success_rate <= 1.0:
                raise ValueError("Min ping success rate must be between 0.0 and 1.0")
            if self.max_failed_streams < 0:
                raise ValueError("Max failed streams must be non-negative")
