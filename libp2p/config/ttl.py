# libp2p/config/ttl.py
from dataclasses import dataclass, field
from typing import Any

import trio


@dataclass
class TTLConfig:
    """Configurable TTL values for different libp2p components."""

    # Peer address TTLs
    peer_addr_ttl: int = 7200  # 2 hours
    temp_addr_ttl: int = 600  # 10 minutes
    permanent_addr_ttl: int = 315360000  # 10 years

    # DHT TTLs
    dht_provider_ttl: int = 86400  # 24 hours
    dht_record_ttl: int = 79200  # 22 hours

    # PubSub TTLs
    pubsub_message_ttl: int = 7200  # 2 hours

    # Identify TTLs
    identify_timeout: int = 30  # 30 seconds

    # Trio-specific: Cleanup tasks for proper resource management
    _cleanup_tasks: list[trio.CancelScope] = field(
        default_factory=list, init=False, repr=False
    )

    @classmethod
    def from_dict(cls, config: dict[str, Any]) -> "TTLConfig":
        """Create TTLConfig from dictionary."""
        return cls(**{k: v for k, v in config.items() if k in cls.__annotations__})

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "peer_addr_ttl": self.peer_addr_ttl,
            "temp_addr_ttl": self.temp_addr_ttl,
            "permanent_addr_ttl": self.permanent_addr_ttl,
            "dht_provider_ttl": self.dht_provider_ttl,
            "dht_record_ttl": self.dht_record_ttl,
            "pubsub_message_ttl": self.pubsub_message_ttl,
            "identify_timeout": self.identify_timeout,
        }

    async def cleanup(self) -> None:
        """Clean up TTL-related resources when cancelled."""
        for task in self._cleanup_tasks:
            task.cancel()
        self._cleanup_tasks.clear()

    def add_cleanup_task(self, task: trio.CancelScope) -> None:
        """Add a cleanup task for proper resource management."""
        self._cleanup_tasks.append(task)  # type: ignore
