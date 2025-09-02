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
    Configuration for multi-connection support.

    This configuration controls how multiple connections per peer are managed,
    including connection limits, timeouts, and load balancing strategies.

    Attributes:
        max_connections_per_peer: Maximum number of connections allowed to a single
                                 peer. Default: 3 connections
        connection_timeout: Timeout in seconds for establishing new connections.
                           Default: 30.0 seconds
        load_balancing_strategy: Strategy for distributing streams across connections.
                                Options: "round_robin" (default) or "least_loaded"

    """

    max_connections_per_peer: int = 3
    connection_timeout: float = 30.0
    load_balancing_strategy: str = "round_robin"  # or "least_loaded"

    def __post_init__(self) -> None:
        """Validate configuration after initialization."""
        if not (
            self.load_balancing_strategy == "round_robin"
            or self.load_balancing_strategy == "least_loaded"
        ):
            raise ValueError(
                "Load balancing strategy can only be 'round_robin' or 'least_loaded'"
            )

        if self.max_connections_per_peer < 1:
            raise ValueError("Max connection per peer should be atleast 1")

        if self.connection_timeout < 0:
            raise ValueError("Connection timeout should be positive")
