"""Lightweight statistics dataclasses used by the service framework."""

from typing import NamedTuple

__all__ = [
    "TaskStats",
    "Stats",
]


class TaskStats(NamedTuple):
    """Statistics for task execution."""

    total_count: int
    finished_count: int

    @property
    def pending_count(self) -> int:  # noqa: D401 – keep simple property
        """Return the number of tasks that are still running."""
        return self.total_count - self.finished_count


class Stats(NamedTuple):
    """Overall service statistics."""

    tasks: TaskStats
