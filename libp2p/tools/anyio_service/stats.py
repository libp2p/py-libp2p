from dataclasses import dataclass


@dataclass
class TaskStats:
    total_count: int
    finished_count: int


@dataclass
class Stats:
    tasks: TaskStats 