"""Task abstractions for the AnyIO service framework."""

from __future__ import annotations

from abc import abstractmethod
from collections import Counter
from collections.abc import Hashable, Iterable, Sequence
from enum import Enum
from typing import TYPE_CHECKING, Any
import uuid

import trio

from .exceptions import DaemonTaskExit, LifecycleError, TooManyChildrenException

if TYPE_CHECKING:
    from .api import ServiceAPI

# Default maximum number of child tasks per parent
MAX_CHILDREN_TASKS = 1000

# Default channel buffer size for task scheduling
CHANNEL_BUFFER = 1000

# Error messages
ERROR_TOO_MANY_CHILDREN = (
    "Task {task} tried to add more than {max_children} child tasks. "
    "Current count: {current_count}. Most common tasks: {most_common}"
)


class TaskType(str, Enum):
    """
    Task type identifiers for internal framework tasks.

    Using an enum ensures no collision with user task names and provides
    a single source of truth for internal task naming.
    """

    USER = "user"
    INTERNAL_SERVICE_RUN = "_internal:service.run"


__all__ = [
    "TaskAPI",
    "TaskWithChildrenAPI",
    "BaseTask",
    "BaseTaskWithChildren",
    "FunctionTask",
    "ChildServiceTask",
    "MAX_CHILDREN_TASKS",
    "CHANNEL_BUFFER",
    "TaskType",
]


# ============================================================================
# Core Task API Abstractions
# ============================================================================


class TaskAPI(Hashable):
    """Abstract base class for tasks in the service framework."""

    name: str
    daemon: bool
    parent: TaskWithChildrenAPI | None

    @abstractmethod
    async def run(self) -> None:
        """Execute the task logic."""
        ...

    @abstractmethod
    async def cancel(self) -> None:
        """Cancel the task."""
        ...

    @property
    @abstractmethod
    def is_done(self) -> bool:
        """Check if the task is completed."""
        ...

    @abstractmethod
    async def wait_done(self) -> None:
        """Wait for the task to complete."""
        ...


class TaskWithChildrenAPI(TaskAPI):
    """Task that can manage child tasks."""

    children: set[TaskAPI]

    @abstractmethod
    def add_child(self, child: TaskAPI) -> None:
        """Add a child task."""
        ...

    @abstractmethod
    def discard_child(self, child: TaskAPI) -> None:
        """Remove a child task."""
        ...


# ============================================================================
# Base Task Implementations
# ============================================================================


class BaseTask(TaskAPI):
    """Base task implementation with common functionality."""

    def __init__(
        self, name: str, daemon: bool, parent: TaskWithChildrenAPI | None
    ) -> None:
        self.name = name
        self.daemon = daemon
        self.parent = parent
        self._id = uuid.uuid4()

    def __hash__(self) -> int:
        return hash(self._id)

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, TaskAPI):
            return hash(self) == hash(other)
        return False

    def __str__(self) -> str:
        return f"{self.name}[daemon={self.daemon}]"


class BaseTaskWithChildren(BaseTask, TaskWithChildrenAPI):
    """Base task that can manage child tasks."""

    def __init__(
        self,
        name: str,
        daemon: bool,
        parent: TaskWithChildrenAPI | None,
        max_children: int = MAX_CHILDREN_TASKS,
    ) -> None:
        super().__init__(name, daemon, parent)
        self.children: set[TaskAPI] = set()
        self._max_children = max_children

    def add_child(self, child: TaskAPI) -> None:
        if len(self.children) >= self._max_children:
            task_counter = Counter(map(str, self.children))
            raise TooManyChildrenException(
                ERROR_TOO_MANY_CHILDREN.format(
                    task=self,
                    max_children=self._max_children,
                    current_count=len(self.children),
                    most_common=task_counter.most_common(10),
                )
            )
        self.children.add(child)

    def discard_child(self, child: TaskAPI) -> None:
        self.children.discard(child)


# ============================================================================
# HIGH COMPLEXITY: FunctionTask with full lifecycle
# ============================================================================


class FunctionTask(BaseTaskWithChildren):
    """
    Task that wraps an async function with full lifecycle management.

    HIGH COMPLEXITY:
    - Tracks the trio task for parent finding
    - Has its own cancel scope for ordered cancellation
    - Waits for children before completing (if not daemon)
    - Manages lifecycle with events
    """

    _trio_task: trio.lowlevel.Task | None = None

    @classmethod
    def iterate_tasks(cls, *tasks: TaskAPI) -> Iterable[FunctionTask]:
        """Iterate over all FunctionTask instances and their children recursively."""
        for task in tasks:
            if isinstance(task, FunctionTask):
                yield task

            if isinstance(task, TaskWithChildrenAPI):
                yield from cls.iterate_tasks(*task.children)

    def __init__(
        self,
        name: str,
        daemon: bool,
        parent: TaskWithChildrenAPI | None,
        async_fn: Any,
        async_fn_args: Sequence[Any],
        count_in_stats: bool = True,
        max_children: int = MAX_CHILDREN_TASKS,
    ) -> None:
        super().__init__(name, daemon, parent, max_children)

        self._async_fn = async_fn
        self._async_fn_args = async_fn_args
        self._count_in_stats = count_in_stats  # Whether to include in user-facing stats

        # Event to track when task is done
        self._done = trio.Event()

        # Cancel scope for ordered cancellation
        self._cancel_scope = trio.CancelScope()  # type: ignore[call-arg]

    # Stats tracking API
    @property
    def count_in_stats(self) -> bool:
        """Return whether this task should be included in user-facing statistics."""
        return self._count_in_stats

    # Trio-specific API for parent tracking
    @property
    def has_trio_task(self) -> bool:
        return self._trio_task is not None

    @property
    def trio_task(self) -> trio.lowlevel.Task:
        if self._trio_task is None:
            raise LifecycleError("Trio task not set yet")
        return self._trio_task

    @trio_task.setter
    def trio_task(self, value: trio.lowlevel.Task) -> None:
        if self._trio_task is not None:
            raise LifecycleError(f"Task already set: {self._trio_task}")
        self._trio_task = value

    # Core TaskAPI implementation
    async def run(self) -> None:
        """
        Run the function with full lifecycle management.

        HIGH COMPLEXITY:
        - Sets trio task for parent finding
        - Runs within cancel scope
        - Enforces daemon behavior
        - Waits for children before completing (if not daemon)
        - Cleans up parent reference
        """
        self.trio_task = trio.lowlevel.current_task()

        try:
            with self._cancel_scope:
                await self._async_fn(*self._async_fn_args)

                if self.daemon:
                    raise DaemonTaskExit(f"Daemon task {self} exited")

                # CRITICAL: Non-daemon tasks wait for all children to complete
                while self.children:
                    await tuple(self.children)[0].wait_done()

        finally:
            self._done.set()
            if self.parent is not None:
                self.parent.discard_child(self)

    async def cancel(self) -> None:
        """
        Cancel this task and all children.

        HIGH COMPLEXITY: Ordered cancellation (children first)
        """
        # Cancel all children first
        for task in tuple(self.children):
            await task.cancel()

        # Then cancel self
        self._cancel_scope.cancel()
        await self.wait_done()

    @property
    def is_done(self) -> bool:
        return self._done.is_set()

    async def wait_done(self) -> None:
        await self._done.wait()


# ============================================================================
# HIGH COMPLEXITY: ChildServiceTask
# ============================================================================


class ChildServiceTask(BaseTask):
    """
    Task that wraps a child service.

    HIGH COMPLEXITY:
    - Creates a manager for the child service
    - Integrates with task hierarchy
    - Proper lifecycle management
    """

    def __init__(
        self,
        name: str,
        daemon: bool,
        parent: TaskWithChildrenAPI | None,
        child_service: ServiceAPI,
    ) -> None:
        super().__init__(name, daemon, parent)

        self._child_service = child_service
        # Import here to avoid circular reference during class definition
        from .manager import AnyIOManager

        self.child_manager: AnyIOManager = AnyIOManager(child_service)

    async def run(self) -> None:
        """Run the child service."""
        if self.child_manager.is_started:
            raise LifecycleError(
                f"Child service {self._child_service} has already been started"
            )

        try:
            await self.child_manager.run()

            if self.daemon:
                raise DaemonTaskExit(f"Daemon task {self} exited")

        finally:
            if self.parent is not None:
                self.parent.discard_child(self)

    async def cancel(self) -> None:
        """Cancel the child service."""
        if self.child_manager.is_started:
            await self.child_manager.stop()

    @property
    def is_done(self) -> bool:
        return self.child_manager.is_finished

    async def wait_done(self) -> None:
        if self.child_manager.is_started:
            await self.child_manager.wait_finished()
