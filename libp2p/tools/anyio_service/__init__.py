"""AnyIO-based service framework (modularized).

This package provides a production-ready service implementation using AnyIO for
structured concurrency and cross-platform async compatibility (asyncio + trio).

The implementation is split across multiple modules for clarity:
- exceptions: Service-specific exception types
- stats: Lightweight statistics dataclasses
- utils: Helper functions
- tasks: Task abstractions and implementations
- manager: AnyIOManager with full lifecycle management
- api: Service APIs, decorators, and base classes
- context: Context managers for running services
"""
from .api import Service, as_service, external_api
from .context import TrioManager, background_trio_service
from .exceptions import (
    DaemonTaskExit,
    LifecycleError,
    ServiceException,
    TooManyChildrenException,
)
from .manager import AnyIOManager
from .stats import Stats, TaskStats
from .tasks import MAX_CHILDREN_TASKS, TaskType
from .utils import get_task_name, is_verbose_logging_enabled

__all__ = [
    # Core service classes (concrete implementations only)
    "Service",
    "AnyIOManager",
    "TrioManager",
    "as_service",
    "background_trio_service",
    # Exceptions
    "ServiceException",
    "DaemonTaskExit",
    "LifecycleError",
    "TooManyChildrenException",
    # Stats
    "Stats",
    "TaskStats",
    # Constants
    "MAX_CHILDREN_TASKS",
    "TaskType",
    # Decorators
    "external_api",
    # Utilities
    "get_task_name",
    "is_verbose_logging_enabled",
]
