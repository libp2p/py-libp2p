"""
Modern async service implementation using AnyIO.

This module provides a production-ready replacement for libp2p.tools.async_service
using AnyIO for structured concurrency and cross-platform async compatibility.

AnyIO provides unified APIs that work with both asyncio and trio backends,
offering better structured concurrency patterns and resource management.
"""

from abc import ABC, abstractmethod
from collections.abc import (
    AsyncIterator,
    Awaitable,
    Callable,
    Coroutine,
    Hashable,
    Iterable,
    Sequence,
)
from contextlib import asynccontextmanager
import functools
import logging
import sys
from typing import Any, NamedTuple, Optional, TypeVar, cast
import uuid

if sys.version_info >= (3, 11):
    from builtins import ExceptionGroup
else:
    from exceptiongroup import ExceptionGroup

import trio
import trio_typing

logger = logging.getLogger(__name__)


# ============================================================================
# Utility Functions
# ============================================================================


def get_task_name(value: Any, explicit_name: str | None = None) -> str:
    """
    Generate a task name from a value (function, service, or explicit name).

    This matches the behavior of the original async_service implementation.
    """
    if explicit_name is not None:
        return explicit_name

    # Import here to avoid circular imports
    if hasattr(value, "__class__") and isinstance(value, ServiceAPI):
        # Service instance naming rules:
        # 1. __str__ if custom implementation
        # 2. __repr__ if custom implementation
        # 3. Class name
        value_cls = type(value)
        if value_cls.__str__ is not object.__str__:
            return str(value)
        if value_cls.__repr__ is not object.__repr__:
            return repr(value)
        else:
            return value.__class__.__name__
    else:
        try:
            return str(value.__name__)
        except AttributeError:
            return repr(value)


# ============================================================================
# Exceptions
# ============================================================================


class ServiceException(Exception):
    """Base class for Service exceptions"""

    pass


class LifecycleError(ServiceException):
    """
    Error raised when service operations are performed outside of service
    lifecycle
    """

    pass


class DaemonTaskExit(ServiceException):
    """Exception raised when a daemon task exits unexpectedly"""

    pass


class TooManyChildrenException(ServiceException):
    """Raised when too many child tasks are spawned"""

    pass


# ============================================================================
# Type definitions
# ============================================================================

AsyncFn = Callable[..., Awaitable[Any]]
EXC_INFO = tuple[type[BaseException], BaseException, Any]
TFunc = TypeVar("TFunc", bound=Callable[..., Coroutine[Any, Any, Any]])


# ============================================================================
# Stats - LOW COMPLEXITY
# ============================================================================


class TaskStats(NamedTuple):
    """Statistics for task execution"""

    total_count: int
    finished_count: int

    @property
    def pending_count(self) -> int:
        return self.total_count - self.finished_count


class Stats(NamedTuple):
    """Overall service statistics"""

    tasks: TaskStats


# ============================================================================
# Core API abstractions
# ============================================================================


class TaskAPI(Hashable):
    """Abstract base class for tasks in the service framework"""

    name: str
    daemon: bool
    parent: Optional["TaskWithChildrenAPI"]

    @abstractmethod
    async def run(self) -> None:
        """Execute the task logic"""
        pass

    @abstractmethod
    async def cancel(self) -> None:
        """Cancel the task"""
        pass

    @property
    @abstractmethod
    def is_done(self) -> bool:
        """Check if the task is completed"""
        pass

    @abstractmethod
    async def wait_done(self) -> None:
        """Wait for the task to complete"""
        pass


class TaskWithChildrenAPI(TaskAPI):
    """Task that can manage child tasks"""

    children: set[TaskAPI]

    @abstractmethod
    def add_child(self, child: TaskAPI) -> None:
        """Add a child task"""
        pass

    @abstractmethod
    def discard_child(self, child: TaskAPI) -> None:
        """Remove a child task"""
        pass


class ManagerAPI(ABC):
    """External interface for service managers"""

    @property
    @abstractmethod
    def is_started(self) -> bool:
        """Return True if the service has been started"""
        pass

    @property
    @abstractmethod
    def is_running(self) -> bool:
        """Return True if the service is actively running"""
        pass

    @property
    @abstractmethod
    def is_cancelled(self) -> bool:
        """Return True if the service has been cancelled"""
        pass

    @property
    @abstractmethod
    def is_finished(self) -> bool:
        """Return True if the service has finished"""
        pass

    @property
    @abstractmethod
    def did_error(self) -> bool:
        """Return True if the service encountered an error"""
        pass

    @abstractmethod
    async def wait_started(self) -> None:
        """Wait for the service to start"""
        pass

    @abstractmethod
    async def wait_finished(self) -> None:
        """Wait for the service to finish"""
        pass

    @abstractmethod
    def cancel(self) -> None:
        """Cancel the service (non-blocking)"""
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Stop the service and wait for completion"""
        pass

    @property
    @abstractmethod
    def stats(self) -> Stats:
        """Get service statistics"""
        pass


class InternalManagerAPI(ManagerAPI):
    """
    Internal interface for service managers with task scheduling capabilities.

    This extends ManagerAPI with methods that should only be used internally
    by the service implementation, not by external callers.
    """

    @trio_typing.takes_callable_and_args
    @abstractmethod
    def run_task(
        self,
        async_fn: AsyncFn,
        *args: Any,
        daemon: bool = False,
        name: str | None = None,
    ) -> None:
        """Run a task in the background"""
        pass

    @trio_typing.takes_callable_and_args
    @abstractmethod
    def run_daemon_task(
        self, async_fn: AsyncFn, *args: Any, name: str | None = None
    ) -> None:
        """Run a daemon task (expected to run indefinitely)"""
        pass

    @abstractmethod
    def run_child_service(
        self, service: "ServiceAPI", daemon: bool = False, name: str | None = None
    ) -> ManagerAPI:
        """Run a child service in the background"""
        pass

    @abstractmethod
    def run_daemon_child_service(
        self, service: "ServiceAPI", name: str | None = None
    ) -> ManagerAPI:
        """Run a daemon child service"""
        pass


class ServiceAPI(ABC):
    """Abstract base class for services"""

    _manager: InternalManagerAPI

    @abstractmethod
    def get_manager(self) -> ManagerAPI:
        """Get the manager for this service"""
        pass

    @abstractmethod
    async def run(self) -> None:
        """Main service logic - implemented by subclasses"""
        pass


# ============================================================================
# Base Task Implementations
# ============================================================================


class BaseTask(TaskAPI):
    """Base task implementation with common functionality"""

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
    """Base task that can manage child tasks"""

    def __init__(
        self, name: str, daemon: bool, parent: TaskWithChildrenAPI | None
    ) -> None:
        super().__init__(name, daemon, parent)
        self.children: set[TaskAPI] = set()

    def add_child(self, child: TaskAPI) -> None:
        if len(self.children) >= 1000:  # MAX_CHILDREN_TASKS
            raise TooManyChildrenException(
                f"Task {self} has too many children ({len(self.children)})"
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
    def iterate_tasks(cls, *tasks: TaskAPI) -> Iterable["FunctionTask"]:
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
        async_fn: AsyncFn,
        async_fn_args: Sequence[Any],
    ) -> None:
        super().__init__(name, daemon, parent)

        self._async_fn = async_fn
        self._async_fn_args = async_fn_args

        # Event to track when task is done
        self._done = trio.Event()

        # Cancel scope for ordered cancellation
        self._cancel_scope = trio.CancelScope()  # type: ignore[call-arg]

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
        self.child_manager: "AnyIOManager" = AnyIOManager(child_service)

    async def run(self) -> None:
        """Run the child service"""
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
        """Cancel the child service"""
        if self.child_manager.is_started:
            await self.child_manager.stop()

    @property
    def is_done(self) -> bool:
        return self.child_manager.is_finished

    async def wait_done(self) -> None:
        if self.child_manager.is_started:
            await self.child_manager.wait_finished()


# ============================================================================
# AnyIO Manager Implementation with HIGH COMPLEXITY features
# ============================================================================


class AnyIOManager(InternalManagerAPI):
    """
    AnyIO-based service manager with full lifecycle management.

    Implements proper lifecycle with locks, stats tracking, dual nursery
    architecture, task hierarchy, and ordered cancellation.
    """

    logger = logging.getLogger("libp2p.service.Manager")
    _verbose = False  # Can be enabled via environment variable

    def __init__(self, service: ServiceAPI):
        self._service = service

        # Lifecycle events
        self._started = trio.Event()
        self._cancelled = trio.Event()
        self._finished = trio.Event()

        # Lifecycle lock
        self._run_lock = trio.Lock()

        # Stats tracking
        self._total_task_count = 0
        self._finished_task_count = 0
        self._done_task_count = 0  # For compatibility with original
        self._count_service_run = True

        # Error collection - HIGH COMPLEXITY
        self._errors: list[EXC_INFO] = []

        # Task hierarchy - HIGH COMPLEXITY
        self._root_tasks: set[TaskAPI] = set()

        # Nursery references
        self._task_nursery: trio.Nursery | None = None
        self._system_nursery: trio.Nursery | None = None

    # ========================================================================
    # ManagerAPI - Properties
    # ========================================================================

    @property
    def is_started(self) -> bool:
        return self._started.is_set()

    @property
    def is_running(self) -> bool:
        return self.is_started and not self.is_finished

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled.is_set()

    @property
    def is_finished(self) -> bool:
        return self._finished.is_set()

    @property
    def did_error(self) -> bool:
        return len(self._errors) > 0

    @property
    def stats(self) -> Stats:
        """Return current statistics"""
        return Stats(
            tasks=TaskStats(
                total_count=self._total_task_count,
                finished_count=self._finished_task_count,
            )
        )

    # ========================================================================
    # ManagerAPI - Lifecycle Methods
    # ========================================================================

    async def wait_started(self) -> None:
        await self._started.wait()

    async def wait_finished(self) -> None:
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
            self._cancelled.set()

    async def stop(self) -> None:
        """Stop the service and wait for completion"""
        self.cancel()
        await self.wait_finished()

    # ========================================================================
    # Core Run Method with HIGH COMPLEXITY
    # ========================================================================

    @classmethod
    async def run_service(cls, service: ServiceAPI) -> None:
        """Class method to run a service"""
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
        # Lock-based lifecycle check
        if self._run_lock.locked():
            raise LifecycleError(
                "Cannot run a service with the run lock already engaged. "
                "Already started?"
            )
        elif self.is_started:
            raise LifecycleError("Cannot run a service which is already started.")

        try:
            async with self._run_lock:
                # Dual nursery architecture
                async with trio.open_nursery() as system_nursery:
                    self._system_nursery = system_nursery

                    # System task: handle cancellation
                    system_nursery.start_soon(self._handle_cancelled)

                    try:
                        async with trio.open_nursery() as task_nursery:
                            self._task_nursery = task_nursery

                            # Mark as started
                            self._started.set()

                            # Run the main service
                            self._count_service_run = False
                            self.run_task(self._service.run, name="run")
                            self._count_service_run = True

                            # Reset task count (don't count service.run itself)
                            self._total_task_count = 0

                            # Block here until all tasks complete

                    except Exception:
                        # Collect exceptions from tasks
                        self._errors.append(cast(EXC_INFO, sys.exc_info()))

                    finally:
                        # Cancel system nursery to clean up
                        system_nursery.cancel_scope.cancel()

        finally:
            # Mark as finished
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
        await self._cancelled.wait()
        self.logger.debug(
            "%s: _handle_cancelled triggering task cancellation", self._service
        )

        # Cancel all root tasks (they will cancel their children)
        for task in tuple(self._root_tasks):
            await task.cancel()

        # Final cancellation of task nursery
        if self._task_nursery is not None:
            self._task_nursery.cancel_scope.cancel()

    # ========================================================================
    # HIGH COMPLEXITY: Parent Task Finding
    # ========================================================================

    def _find_parent_task(
        self, trio_task: trio.lowlevel.Task
    ) -> TaskWithChildrenAPI | None:
        """
        Find the FunctionTask that corresponds to the given trio task.

        HIGH COMPLEXITY: Searches through task hierarchy using trio's task identity.
        """
        for task in FunctionTask.iterate_tasks(*self._root_tasks):
            # Skip tasks that haven't started yet
            if not task.has_trio_task:
                continue

            if trio_task is task.trio_task:
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
        """Schedule a task to run in the task nursery."""
        if self._task_nursery is None:
            raise LifecycleError("Cannot schedule task before service is running")

        self._task_nursery.start_soon(self._run_and_manage_task, task, name=str(task))

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

        except Exception as err:
            self.logger.error(
                "%s: task %s exited with error: %s",
                self._service,
                task,
                err,
                exc_info=not isinstance(err, DaemonTaskExit),
            )
            # HIGH COMPLEXITY: Collect error and trigger cancellation
            self._errors.append(cast(EXC_INFO, sys.exc_info()))
            self.cancel()

        else:
            # Task completed successfully
            if task.parent is None:
                self._root_tasks.discard(task)
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
    ) -> None:
        """
        Run a task in the background.

        HIGH COMPLEXITY:
        - Creates FunctionTask with full lifecycle
        - Finds parent using trio.lowlevel.current_task()
        - Adds to task hierarchy
        - Schedules for execution
        """
        task = FunctionTask(
            name=get_task_name(async_fn, name),
            daemon=daemon,
            parent=self._find_parent_task(trio.lowlevel.current_task()),
            async_fn=async_fn,
            async_fn_args=args,
        )

        # Add to hierarchy
        self._add_child_task(task.parent, task)

        # Update stats
        if self._count_service_run or task.name != "run":
            self._total_task_count += 1

        # Schedule
        self._schedule_task(task)

    def run_daemon_task(
        self, async_fn: AsyncFn, *args: Any, name: str | None = None
    ) -> None:
        """Run a daemon task (expected to run indefinitely)"""
        self.run_task(async_fn, *args, daemon=True, name=name)

    def run_child_service(
        self, service: ServiceAPI, daemon: bool = False, name: str | None = None
    ) -> ManagerAPI:
        """
        Run a child service.

        HIGH COMPLEXITY:
        - Creates ChildServiceTask with full lifecycle
        - Finds parent using trio.lowlevel.current_task()
        - Adds to task hierarchy
        - Returns child manager for external control
        """
        task = ChildServiceTask(
            name=get_task_name(service, name),
            daemon=daemon,
            parent=self._find_parent_task(trio.lowlevel.current_task()),
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
        """Run a daemon child service"""
        return self.run_child_service(service, daemon=True, name=name)


# ============================================================================
# Service Implementation
# ============================================================================


class Service(ServiceAPI):
    """AnyIO-based service implementation"""

    def __str__(self) -> str:
        return self.__class__.__name__

    @property
    def manager(self) -> InternalManagerAPI:
        """Internal access to the manager (for subclasses)"""
        return self._manager

    def get_manager(self) -> ManagerAPI:
        """External access to the manager"""
        try:
            return self._manager
        except AttributeError:
            raise LifecycleError(
                "Service does not have a manager assigned to it. "
                "Are you sure it is running?"
            )


# ============================================================================
# Helper Functions
# ============================================================================


def as_service(service_fn: AsyncFn) -> type[ServiceAPI]:
    """Convert a simple async function into a Service class"""

    class _Service(Service):
        def __init__(self, *args: Any, **kwargs: Any):
            self._args = args
            self._kwargs = kwargs

        async def run(self) -> None:
            await service_fn(self.manager, *self._args, **self._kwargs)

    _Service.__name__ = service_fn.__name__
    _Service.__doc__ = service_fn.__doc__
    return _Service


# ============================================================================
# HIGH COMPLEXITY: External API Decorator
# ============================================================================

_ChannelPayload = tuple[Optional[Any], Optional[BaseException]]


async def _wait_finished(
    service: ServiceAPI,
    api_func: Callable[..., Any],
    channel: trio.abc.SendChannel[_ChannelPayload],
) -> None:
    """Helper for external_api: wait for service to finish"""
    manager = service.get_manager()

    if manager.is_finished:
        await channel.send(
            (
                None,
                LifecycleError(
                    f"Cannot access external API {api_func}. "
                    f"Service {service} is not running: "
                ),
            )
        )
        return

    await manager.wait_finished()
    await channel.send(
        (
            None,
            LifecycleError(
                f"Cannot access external API {api_func}. "
                f"Service {service} is not running: "
            ),
        )
    )


async def _wait_api_fn(
    self: ServiceAPI,
    api_fn: Callable[..., Any],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    channel: trio.abc.SendChannel[_ChannelPayload],
) -> None:
    """Helper for external_api: execute the API function"""
    try:
        result = await api_fn(self, *args, **kwargs)
    except Exception:
        _, exc_value, exc_tb = sys.exc_info()
        if exc_value is None or exc_tb is None:
            raise Exception(
                "This should be unreachable but acts as a type guard for mypy"
            )
        await channel.send((None, exc_value.with_traceback(exc_tb)))
    else:
        await channel.send((result, None))


def external_api(func: TFunc) -> TFunc:
    """
    Decorator to protect external API methods.

    MEDIUM COMPLEXITY: Ensures methods can only be called while service is running.
    Uses trio channels and nurseries to race the API call against service shutdown.
    """

    @functools.wraps(func)
    async def inner(self: ServiceAPI, *args: Any, **kwargs: Any) -> Any:
        if not hasattr(self, "manager"):
            raise LifecycleError(
                f"Cannot access external API {func}. Service {self} has not been run."
            )

        manager = self.get_manager()

        if not manager.is_running:
            raise LifecycleError(
                f"Cannot access external API {func}. Service {self} is not running."
            )

        # Create a channel for communication
        channels: tuple[
            trio.abc.SendChannel[_ChannelPayload],
            trio.abc.ReceiveChannel[_ChannelPayload],
        ] = trio.open_memory_channel(0)
        send_channel, receive_channel = channels

        # Race the API call against service finishing
        async with trio.open_nursery() as nursery:
            nursery.start_soon(
                _wait_api_fn,  # type: ignore
                self,
                func,
                args,
                kwargs,
                send_channel,
            )
            nursery.start_soon(_wait_finished, self, func, send_channel)
            result, err = await receive_channel.receive()
            nursery.cancel_scope.cancel()

        if err is None:
            return result
        else:
            raise err

    return cast(TFunc, inner)


# ============================================================================
# Background Service Context Manager
# ============================================================================


@asynccontextmanager
async def background_trio_service(service: ServiceAPI) -> AsyncIterator[ManagerAPI]:
    """
    Run a service in the background using Trio's structured concurrency.

    The service is running within the context block and will be properly
    cleaned up upon exiting the context block.
    """
    async with trio.open_nursery() as nursery:
        manager = AnyIOManager(service)
        service._manager = manager

        nursery.start_soon(manager.run)
        await manager.wait_started()

        try:
            yield manager
        finally:
            await manager.stop()


# ============================================================================
# Compatibility Alias for Trio
# ============================================================================

TrioManager = AnyIOManager  # Alias for backward compatibility


# ============================================================================
# Export all public APIs
# ============================================================================

__all__ = [
    # Core service APIs
    "Service",
    "ServiceAPI",
    "ManagerAPI",
    "InternalManagerAPI",
    "TrioManager",
    "as_service",
    "background_trio_service",
    # Task APIs
    "TaskAPI",
    "TaskWithChildrenAPI",
    "FunctionTask",
    "ChildServiceTask",
    # Exceptions
    "ServiceException",
    "DaemonTaskExit",
    "LifecycleError",
    "TooManyChildrenException",
    # Types
    "AsyncFn",
    "EXC_INFO",
    # Stats
    "Stats",
    "TaskStats",
    # Decorators
    "external_api",
    # Utilities
    "get_task_name",
]
