# Copied from https://github.com/ethereum/async-service

from typing import (
    NamedTuple,
)


class TaskStats(NamedTuple):
    total_count: int
    finished_count: int

    @property
    def pending_count(self) -> int:
        return self.total_count - self.finished_count


class Stats(NamedTuple):
    tasks: TaskStats
