"""Service manager implementation with lifecycle management."""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING, Any, cast

if sys.version_info >= (3, 11):
    from builtins import ExceptionGroup
else:
    from exceptiongroup import ExceptionGroup

import anyio
from anyio import TaskInfo
from anyio.abc import TaskGroup

if TYPE_CHECKING:
    from anyio.abc import Event, Lock

from .api import InternalManagerAPI
from .exceptions import DaemonTaskExit, LifecycleError
from .stats import Stats, TaskStats
from .tasks import (
    MAX_CHILDREN_TASKS,
    ChildServiceTask,
    FunctionTask,
    TaskAPI,
    TaskType,
    TaskWithChildrenAPI,
)
from .utils import get_task_name, is_verbose_logging_enabled

if TYPE_CHECKING:
    from .api import AsyncFn, ManagerAPI, ServiceAPI

__all__ = ["AnyIOManager"]

# Type alias for exception info tuples
EXC_INFO = tuple[type[BaseException], BaseException, Any]

# Error messages
ERROR_SERVICE_CANCELLED = "Service {service} cancelled: {msg}"
ERROR_SERVICE_EXIT = "Service {service} exited: {msg}"
ERROR_SERVICE_TASK_ERROR = (
    "Service {service} task {task} {msg} with {exc_type}: {exc_value}"
)
ERROR_CANNOT_SCHEDULE_AFTER_STOP = "Cannot schedule task after service has stopped"


class AnyIOManager(InternalManagerAPI):
    """
    AnyIO-based service manager with full lifecycle management.

    Implements proper lifecycle with locks, stats tracking, dual nursery
    architecture, task hierarchy, and ordered cancellation.
    """

    def __init__(
        self,
        service: ServiceAPI,
        max_children_per_task: int = MAX_CHILDREN_TASKS,
        logger: logging.Logger | None = None,
    ):
        self._service = service
        self._max_children_per_task = max_children_per_task

        # Allow custom logger or create per-service logger for better filtering
        if logger is not None:
            self.logger = logger
        else:
            service_name = service.__class__.__name__
            self.logger = logging.getLogger(
                f"libp2p.tools.anyio_service.Manager.{service_name}"
            )

        # Enable verbose logging from environment variable
        self._verbose = is_verbose_logging_enabled()

        # Lifecycle events (created lazily to avoid async context requirement)
        self._started: Event | None = None
        self._finished: Event | None = None

        # Cancellation flag (sync, since cancel() must be non-async per API)
        self._cancel_requested: bool = False

        # Lifecycle lock (created lazily to avoid async context requirement)
        self._run_lock: Lock | None = None

        # Stats tracking
        self._total_task_count = 0
        self._finished_task_count = 0
        self._done_task_count = 0  # For compatibility with original

        # Error collection - HIGH COMPLEXITY
        self._errors: list[EXC_INFO] = []

        # Task hierarchy - HIGH COMPLEXITY
        self._root_tasks: set[TaskAPI] = set()

        # Task group references (formerly nurseries)
        self._task_nursery: TaskGroup | None = None
        self._system_nursery: TaskGroup | None = None

        # Task queue for synchronous scheduling with async spawn
        self._task_queue: list[tuple[TaskAPI, str]] = []
        self._has_queued_tasks: bool = False

    def __str__(self) -> str:
        """String representation of the manager."""
        return f"AnyIOManager[{self._service}]"

    # ========================================================================
    # ManagerAPI - Properties
    # ========================================================================

    @property
    def is_started(self) -> bool:
        return bool(self._started is not None and self._started.is_set())

    @property
    def is_running(self) -> bool:
        return self.is_started and not self.is_finished

    @property
    def is_cancelled(self) -> bool:
        return self._cancel_requested

    @property
    def is_finished(self) -> bool:
        return bool(self._finished is not None and self._finished.is_set())

    @property
    def did_error(self) -> bool:
        return len(self._errors) > 0

    @property
    def stats(self) -> Stats:
        """Return current statistics."""
        return Stats(
            tasks=TaskStats(
                total_count=self._total_task_count,
                finished_count=self._finished_task_count,
            )
        )

    # ========================================================================
    # ManagerAPI - Lifecycle Methods
    # ========================================================================

    async def _ensure_initialized(self) -> None:
        """Ensure lifecycle primitives are initialized (called from async context)."""
        if self._started is None:
            self._started = anyio.Event()
            self._finished = anyio.Event()
            self._run_lock = anyio.Lock()

    async def wait_started(self) -> None:
        await self._ensure_initialized()
        assert self._started is not None
        await self._started.wait()

    async def wait_finished(self) -> None:
        await self._ensure_initialized()
        assert self._finished is not None
        await self._finished.wait()

    def cancel(self) -> None:
        """
        Cancel the service (non-blocking).

        HIGH COMPLEXITY: Enhanced validation and state management.
        """
        if not self.is_started:
            raise LifecycleError("Cannot cancel a service which was never started.")
        elif not self.is_running:
            return
        else:
            self._cancel_requested = True

    async def stop(self) -> None:
        """Stop the service and wait for completion."""
        self.cancel()
        await self.wait_finished()

    # ========================================================================
    # Core Run Method with HIGH COMPLEXITY
    # ========================================================================

    @classmethod
    async def run_service(cls, service: ServiceAPI) -> None:
        """Class method to run a service."""
        manager = cls(service)
        await manager.run()

    async def run(self) -> None:
        """
        Main run loop with proper lifecycle management.

        HIGH COMPLEXITY:
        - Lock-based lifecycle protection
        - Dual nursery architecture (system + task)
        - Cancellation handler
        - Error collection and propagation
        - Proper cleanup on exit
        """
        # Initialize lifecycle primitives (must be done in async context for AnyIO)
        await self._ensure_initialized()
        assert self._run_lock is not None
        assert self._started is not None
        assert self._finished is not None

        # Lock-based lifecycle check
        if self._run_lock.locked():
            raise LifecycleError(
                "Cannot run a service with the run lock already engaged. "
                "Already started?"
            )
        elif self.is_started:
            raise LifecycleError("Cannot run a service which is already started.")

        # Assign manager to service so it can access it
        self._service._manager = self

        try:
            async with self._run_lock:
                # Dual task group architecture (formerly nurseries)
                async with anyio.create_task_group() as system_nursery:
                    self._system_nursery = system_nursery

                    # System tasks
                    system_nursery.start_soon(self._handle_cancelled)  # type: ignore[arg-type]
                    system_nursery.start_soon(self._task_spawner)  # type: ignore[arg-type]

                    try:
                        async with anyio.create_task_group() as task_nursery:
                            self._task_nursery = task_nursery

                            # Mark as started
                            if self._started is not None:
                                self._started.set()

                            # Run the main service (internal task, not counted in stats)
                            self.run_task(
                                self._service.run,
                                name=TaskType.INTERNAL_SERVICE_RUN.value,
                                _internal=True,
                            )

                            # Block here until all tasks complete

                    except Exception as exc:
                        # Collect exceptions from tasks
                        # Handle both single exceptions and ExceptionGroups
                        if isinstance(exc, ExceptionGroup):
                            # Extract individual exceptions from the group
                            for sub_exc in exc.exceptions:
                                self._errors.append(
                                    (type(sub_exc), sub_exc, sub_exc.__traceback__)
                                )
                        else:
                            self._errors.append(cast(EXC_INFO, sys.exc_info()))

                    finally:
                        # Cancel system task group to clean up
                        if system_nursery.cancel_scope is not None:
                            system_nursery.cancel_scope.cancel()

        finally:
            # Mark as finished
            if self._finished is not None:
                self._finished.set()
            self.logger.debug("%s: finished", self._service)

        # HIGH COMPLEXITY: Raise collected errors
        if self.did_error:
            raise ExceptionGroup(
                "Encountered multiple Exceptions: ",
                tuple(
                    exc_value.with_traceback(exc_tb)
                    for _, exc_value, exc_tb in self._errors
                    if isinstance(exc_value, Exception)
                ),
            )

    # ========================================================================
    # System Tasks - HIGH COMPLEXITY
    # ========================================================================

    async def _handle_cancelled(self) -> None:
        """
        System task that handles cancellation requests.

        HIGH COMPLEXITY: Ordered cancellation of root tasks.
        """
        self.logger.debug(
            "%s: _handle_cancelled waiting for cancellation", self._service
        )
        # Poll for cancellation (since cancel() is sync, we use a flag)
        while not self._cancel_requested:
            await anyio.sleep(0)  # Yield to other tasks without delay

        self.logger.debug(
            "%s: _handle_cancelled triggering task cancellation", self._service
        )

        # Cancel all root tasks (they will cancel their children)
        for task in tuple(self._root_tasks):
            await task.cancel()

    # ========================================================================
    # HIGH COMPLEXITY: Parent Task Finding
    # ========================================================================

    def _find_parent_task(self, anyio_task: TaskInfo) -> TaskWithChildrenAPI | None:
        """
        Find the FunctionTask that corresponds to the given anyio task.

        HIGH COMPLEXITY: Searches through task hierarchy using anyio's task identity.
        """
        for task in FunctionTask.iterate_tasks(*self._root_tasks):
            # Skip tasks that haven't started yet
            if not task.has_anyio_task:
                continue

            if anyio_task is task.anyio_task:
                return task

        # No match = new root task
        return None

    # ========================================================================
    # HIGH COMPLEXITY: Task Management
    # ========================================================================

    def _add_child_task(
        self, parent: TaskWithChildrenAPI | None, task: TaskAPI
    ) -> None:
        """Add a task to its parent or to root tasks."""
        if parent is None:
            self._root_tasks.add(task)
        else:
            parent.add_child(task)

    def _schedule_task(self, task: TaskAPI) -> None:
        """Schedule a task to run in the task group."""
        if self._task_nursery is None:
            raise LifecycleError("Cannot schedule task before service is running")

        if not self.is_running:
            raise LifecycleError(ERROR_CANNOT_SCHEDULE_AFTER_STOP)

        # Spawn task immediately (start_soon is synchronous in anyio)
        self._task_nursery.start_soon(self._run_and_manage_task, task, name=str(task))

    async def _task_spawner(self) -> None:
        """Background task (kept for compatibility, tasks now spawn synchronously)."""
        # Tasks are now spawned synchronously in _schedule_task,
        # so this just waits to be cancelled
        try:
            while self.is_running:
                await anyio.sleep(0.1)
        except anyio.get_cancelled_exc_class():
            # Gracefully handle cancellation
            pass

    async def _run_and_manage_task(self, task: TaskAPI) -> None:
        """
        Run and manage a task's lifecycle.

        HIGH COMPLEXITY:
        - Proper error collection
        - DaemonTaskExit handling
        - Orphaned child reassignment (DEFERRED)
        - Task cleanup
        - Error triggers cancellation
        """
        if self._verbose:
            self.logger.debug("%s: task %s running", self._service, task)

        try:
            try:
                await task.run()

            except DaemonTaskExit:
                # DaemonTaskExit is only an error if we're not cancelled
                if self.is_cancelled:
                    pass
                else:
                    raise

            finally:
                # CRITICAL: Orphaned child reassignment
                # If a task exits with children, reassign them to grandparent
                if isinstance(task, TaskWithChildrenAPI):
                    new_parent = task.parent
                    for child in task.children:
                        child.parent = new_parent
                        self._add_child_task(new_parent, child)
                        self.logger.debug(
                            "%s left a child task (%s) behind, reassigning it to %s",
                            task,
                            child,
                            new_parent or "root",
                        )

        except anyio.get_cancelled_exc_class():
            # Cancellation is expected during shutdown, not an error
            if self._verbose:
                self.logger.debug("%s: task %s was cancelled", self._service, task)
            # Don't collect as error or trigger additional cancellation
            # But still clean up root task tracking
            if task.parent is None:
                self._root_tasks.discard(task)

        except Exception as err:
            self.logger.error(
                "%s: task %s exited with error: %s",
                self._service,
                task,
                err,
                exc_info=not isinstance(err, DaemonTaskExit),
            )
            # HIGH COMPLEXITY: Trigger cancellation and re-raise
            # Don't collect here - let the outer task_group handler collect
            self.logger.debug("%s: calling cancel() due to exception", self._service)
            self.cancel()
            self.logger.debug(
                "%s: cancel() called, is_cancelled=%s",
                self._service,
                self.is_cancelled,
            )
            # Re-raise so AnyIO's task group can cancel all other tasks immediately
            raise

        else:
            # Task completed successfully
            if task.parent is None:
                self._root_tasks.discard(task)
            # Only count user tasks in finished stats (not internal framework tasks)
            if isinstance(task, FunctionTask) and task.count_in_stats:
                self._finished_task_count += 1
            if self._verbose:
                self.logger.debug("%s: task %s exited cleanly.", self._service, task)

        finally:
            self._done_task_count += 1

    # ========================================================================
    # InternalManagerAPI - Task Scheduling with HIGH COMPLEXITY
    # ========================================================================

    def run_task(
        self,
        async_fn: AsyncFn,
        *args: Any,
        daemon: bool = False,
        name: str | None = None,
        _internal: bool = False,
    ) -> None:
        """
        Run a task in the background.

        HIGH COMPLEXITY:
        - Creates FunctionTask with full lifecycle
        - Finds parent using anyio.get_current_task()
        - Adds to task hierarchy
        - Schedules for execution
        """
        count_in_stats = not _internal

        # Find parent task in the task hierarchy
        current_anyio_task = anyio.get_current_task()
        parent = self._find_parent_task(current_anyio_task)

        task = FunctionTask(
            name=get_task_name(async_fn, name),
            daemon=daemon,
            parent=parent,
            async_fn=async_fn,
            async_fn_args=args,
            count_in_stats=count_in_stats,
            max_children=self._max_children_per_task,
        )

        # Add to hierarchy
        self._add_child_task(task.parent, task)

        # Update stats (only count user tasks)
        if count_in_stats:
            self._total_task_count += 1

        # Schedule
        self._schedule_task(task)

    def run_daemon_task(
        self, async_fn: AsyncFn, *args: Any, name: str | None = None
    ) -> None:
        """Run a daemon task (expected to run indefinitely)."""
        self.run_task(async_fn, *args, daemon=True, name=name)

    def run_child_service(
        self, service: ServiceAPI, daemon: bool = False, name: str | None = None
    ) -> ManagerAPI:
        """
        Run a child service.

        HIGH COMPLEXITY:
        - Creates ChildServiceTask with full lifecycle
        - Finds parent using anyio.get_current_task()
        - Adds to task hierarchy
        - Returns child manager for external control
        """
        # Find parent task in the task hierarchy
        current_anyio_task = anyio.get_current_task()
        parent = self._find_parent_task(current_anyio_task)

        task = ChildServiceTask(
            name=get_task_name(service, name),
            daemon=daemon,
            parent=parent,
            child_service=service,
        )

        # Add to hierarchy
        self._add_child_task(task.parent, task)

        # Schedule
        self._schedule_task(task)

        return task.child_manager

    def run_daemon_child_service(
        self, service: ServiceAPI, name: str | None = None
    ) -> ManagerAPI:
        """Run a daemon child service."""
        return self.run_child_service(service, daemon=True, name=name)
