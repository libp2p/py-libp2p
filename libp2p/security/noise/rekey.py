"""Rekey support for Noise protocol sessions."""

from abc import ABC, abstractmethod
import time
from typing import Protocol, runtime_checkable


@runtime_checkable
class RekeyPolicy(Protocol):
    """Protocol for rekey policies."""

    def should_rekey(self, bytes_processed: int, time_elapsed: float) -> bool:
        """
        Determine if a rekey should be performed.

        Args:
            bytes_processed: Number of bytes processed since last rekey
            time_elapsed: Time elapsed since last rekey in seconds

        Returns:
            bool: True if rekey should be performed

        """
        ...


class TimeBasedRekeyPolicy(RekeyPolicy):
    """Rekey policy based on time elapsed."""

    def __init__(self, max_time_seconds: int = 3600):  # 1 hour default
        """
        Initialize with maximum time between rekeys.

        Args:
            max_time_seconds: Maximum time between rekeys in seconds

        """
        self.max_time_seconds = max_time_seconds

    def should_rekey(self, bytes_processed: int, time_elapsed: float) -> bool:
        """
        Check if rekey should be performed based on time.

        Args:
            bytes_processed: Number of bytes processed (ignored for time-based policy)
            time_elapsed: Time elapsed since last rekey in seconds

        Returns:
            bool: True if maximum time has been exceeded

        """
        return time_elapsed >= self.max_time_seconds


class ByteCountRekeyPolicy(RekeyPolicy):
    """Rekey policy based on bytes processed."""

    def __init__(self, max_bytes: int = 1024 * 1024 * 1024):  # 1GB default
        """
        Initialize with maximum bytes between rekeys.

        Args:
            max_bytes: Maximum bytes processed between rekeys

        """
        self.max_bytes = max_bytes

    def should_rekey(self, bytes_processed: int, time_elapsed: float) -> bool:
        """
        Check if rekey should be performed based on bytes processed.

        Args:
            bytes_processed: Number of bytes processed since last rekey
            time_elapsed: Time elapsed (ignored for byte-based policy)

        Returns:
            bool: True if maximum bytes have been processed

        """
        return bytes_processed >= self.max_bytes


class CompositeRekeyPolicy(RekeyPolicy):
    """Rekey policy that combines multiple policies."""

    def __init__(self, policies: list[RekeyPolicy]):
        """
        Initialize with a list of rekey policies.

        Args:
            policies: List of rekey policies to combine

        """
        self.policies = policies

    def should_rekey(self, bytes_processed: int, time_elapsed: float) -> bool:
        """
        Check if rekey should be performed based on any policy.

        Args:
            bytes_processed: Number of bytes processed since last rekey
            time_elapsed: Time elapsed since last rekey in seconds

        Returns:
            bool: True if any policy indicates rekey should be performed

        """
        return any(
            policy.should_rekey(bytes_processed, time_elapsed)
            for policy in self.policies
        )


class RekeyManager:
    """Manager for rekey operations in Noise sessions."""

    def __init__(self, policy: RekeyPolicy | None = None):
        """
        Initialize with an optional rekey policy.

        Args:
            policy: Rekey policy to use

        """
        self.policy = policy or CompositeRekeyPolicy(
            [
                TimeBasedRekeyPolicy(max_time_seconds=3600),  # 1 hour
                ByteCountRekeyPolicy(max_bytes=1024 * 1024 * 1024),  # 1GB
            ]
        )

        self._last_rekey_time = time.time()
        self._bytes_since_rekey = 0
        self._rekey_count = 0

    def update_bytes_processed(self, bytes_count: int) -> None:
        """
        Update the count of bytes processed since last rekey.

        Args:
            bytes_count: Number of bytes processed

        """
        self._bytes_since_rekey += bytes_count

    def should_rekey(self) -> bool:
        """
        Check if a rekey should be performed.

        Returns:
            bool: True if rekey should be performed

        """
        time_elapsed = time.time() - self._last_rekey_time
        return self.policy.should_rekey(self._bytes_since_rekey, time_elapsed)

    def perform_rekey(self) -> None:
        """Mark that a rekey has been performed."""
        self._last_rekey_time = time.time()
        self._bytes_since_rekey = 0
        self._rekey_count += 1

    def get_stats(self) -> dict[str, int | float]:
        """
        Get rekey statistics.

        Returns:
            dict: Statistics about rekey operations

        """
        time_elapsed = time.time() - self._last_rekey_time
        return {
            "rekey_count": self._rekey_count,
            "bytes_since_rekey": self._bytes_since_rekey,
            "time_since_rekey": time_elapsed,
            "last_rekey_time": self._last_rekey_time,
        }

    def reset_stats(self) -> None:
        """Reset rekey statistics."""
        self._last_rekey_time = time.time()
        self._bytes_since_rekey = 0
        self._rekey_count = 0


class RekeyableSession(ABC):
    """Abstract base class for sessions that support rekeying."""

    @abstractmethod
    async def rekey(self) -> None:
        """
        Perform a rekey operation.

        Raises:
            Exception: If rekey operation fails

        """
        pass


class RekeyHandler:
    """Handler for managing rekey operations in Noise sessions."""

    def __init__(
        self, session: RekeyableSession, rekey_manager: RekeyManager | None = None
    ):
        """
        Initialize with a rekeyable session and optional rekey manager.

        Args:
            session: Session that supports rekeying
            rekey_manager: Rekey manager to use

        """
        self.session = session
        self.rekey_manager = rekey_manager or RekeyManager()

    async def check_and_rekey(self, bytes_processed: int = 0) -> bool:
        """
        Check if rekey is needed and perform it if necessary.

        Args:
            bytes_processed: Number of bytes processed in this operation

        Returns:
            bool: True if rekey was performed

        Raises:
            Exception: If rekey operation fails

        """
        if bytes_processed > 0:
            self.rekey_manager.update_bytes_processed(bytes_processed)

        if self.rekey_manager.should_rekey():
            await self.session.rekey()
            self.rekey_manager.perform_rekey()
            return True

        return False

    def get_rekey_stats(self) -> dict[str, int | float]:
        """
        Get rekey statistics.

        Returns:
            dict: Statistics about rekey operations

        """
        return self.rekey_manager.get_stats()

    def set_rekey_policy(self, policy: RekeyPolicy) -> None:
        """
        Set a new rekey policy.

        Args:
            policy: Rekey policy to use

        """
        self.rekey_manager.policy = policy
