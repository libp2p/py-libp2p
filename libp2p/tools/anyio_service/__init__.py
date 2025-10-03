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
from .api import (
    AsyncFn,
    InternalManagerAPI,
    ManagerAPI,
    Service,
    ServiceAPI,
    as_service,
    external_api,
)
from .context import TrioManager, background_trio_service
from .exceptions import (
    DaemonTaskExit,
    LifecycleError,
    ServiceException,
    TooManyChildrenException,
)
from .manager import AnyIOManager
from .stats import Stats, TaskStats
from .tasks import (
    BaseTask,
    BaseTaskWithChildren,
    CHANNEL_BUFFER,
    ChildServiceTask,
    FunctionTask,
    MAX_CHILDREN_TASKS,
    TaskAPI,
    TaskType,
    TaskWithChildrenAPI,
)
from .utils import get_task_name, is_verbose_logging_enabled

__all__ = [
    # Core service APIs
    "Service",
    "ServiceAPI",
    "ManagerAPI",
    "InternalManagerAPI",
    "AnyIOManager",
    "TrioManager",
    "as_service",
    "background_trio_service",
    # Task APIs
    "TaskAPI",
    "TaskWithChildrenAPI",
    "BaseTask",
    "BaseTaskWithChildren",
    "FunctionTask",
    "ChildServiceTask",
    "TaskType",
    # Exceptions
    "ServiceException",
    "DaemonTaskExit",
    "LifecycleError",
    "TooManyChildrenException",
    # Stats
    "Stats",
    "TaskStats",
    # Types
    "AsyncFn",
    # Constants
    "MAX_CHILDREN_TASKS",
    "CHANNEL_BUFFER",
    # Decorators
    "external_api",
    # Utilities
    "get_task_name",
    "is_verbose_logging_enabled",
]
