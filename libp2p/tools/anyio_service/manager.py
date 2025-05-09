"""
Manager implementation using AnyIO's structured concurrency.
"""
# mypy: disable-error-code="unused-coroutine"

from collections.abc import (
    AsyncIterator,
    Awaitable,
)
from contextlib import (
    asynccontextmanager,
)
from functools import (
    wraps,
)
import logging
import sys
from typing import (
    Any,
    Callable,
    TypeVar,
)

import anyio
from anyio.abc import (
    CancelScope,
    TaskGroup,
)

from .abc import (
    InternalManagerAPI,
    ManagerAPI,
    ServiceAPI,
)
from .exceptions import (
    DaemonTaskExit,
    LifecycleError,
)
from .stats import (
    Stats,
    TaskStats,
)
from .utils import (
    as_service,
)

T = TypeVar("T")


class AnyIOManager(InternalManagerAPI):
    """
    Manager implementation using AnyIO's structured concurrency.
    """

    logger = logging.getLogger("async_service.AnyIOManager")

    def __init__(self, service: ServiceAPI) -> None:
        """
        Initialize the manager with a service.

        Args
        ----
            service: The service to manage.

        Raises
        ------
            LifecycleError: If the service already has a manager.

        """
        if service.get_manager() is not None:
            raise LifecycleError("Service already has a manager.")
        service.manager = self
        self._service = service
        self._errors: list[tuple[type, BaseException, Any]] = []

        self._started = False
        self._running = False
        self._cancelled = False
        self._finished = False

        self._total_task_count = 0
        self._done_task_count = 0

        self._started_event = anyio.create_event()
        self._finished_event = anyio.create_event()

        self._task_group: TaskGroup | None = None
        self._cancel_scope: CancelScope | None = None

    def __str__(self) -> str:
        """Return a string representation of the manager."""
        status_flags = "".join(
            (
                "S" if self.is_started else "s",
                "R" if self.is_running else "r",
                "C" if self.is_cancelled else "c",
                "F" if self.is_finished else "f",
                "E" if self.did_error else "e",
            )
        )
        return f"<AnyIOManager[{self._service}] flags={status_flags}>"

    @property
    def is_started(self) -> bool:
        """Return whether the service has started."""
        return self._started

    @property
    def is_running(self) -> bool:
        """Return whether the service is running."""
        return self._running

    @property
    def is_cancelled(self) -> bool:
        """Return whether the service has been cancelled."""
        return self._cancelled

    @property
    def is_finished(self) -> bool:
        """Return whether the service has finished."""
        return self._finished

    @property
    def did_error(self) -> bool:
        """Return whether the service encountered an error."""
        return len(self._errors) > 0

    def cancel(self) -> None:
        """Cancel the service if it hasn't been cancelled already."""
        if not self._cancelled and self._cancel_scope is not None:
            self._cancelled = True
            self._cancel_scope.cancel()  # type: ignore

    async def stop(self) -> None:
        """Stop the service and wait for it to finish."""
        self.cancel()
        await self.wait_finished()

    async def wait_started(self) -> None:
        """Wait for the service to start."""
        await self._started_event.wait()

    async def wait_finished(self) -> None:
        """Wait for the service to finish."""
        await self._finished_event.wait()

    async def run(self) -> None:
        """
        Run the service.

        Raises
        ------
            RuntimeError: If the service is already running.

        """
        if self._task_group is not None:
            raise RuntimeError("Service already running")

        async with anyio.create_task_group() as task_group:
            self._task_group = task_group
            async with anyio.open_cancel_scope() as cancel_scope:
                self._cancel_scope = cancel_scope
                self._started = True
                self._running = True
                self._started_event.set()
                try:
                    await self._service.run()
                except Exception:
                    self._errors.append(sys.exc_info())
                    self.logger.exception(
                        "Service %s raised an exception", self._service
                    )
                    self.cancel()
                    raise
                finally:
                    self._running = False
                    self._finished = True
                    self._finished_event.set()
                    self._task_group = None
                    self._cancel_scope = None

    @classmethod
    async def run_service(cls, service: ServiceAPI) -> None:
        """
        Run a service.

        This method creates a new AnyIOManager to run the given service.

        Args:
        ----
            service: The service to run.

        """
        manager = cls(service)
        await manager.run()

    def run_task(
        self,
        async_fn: Callable[..., Awaitable[Any]],
        *args: Any,
        daemon: bool = False,
        name: str | None = None,
    ) -> None:
        """
        Run a task in the service.

        Args
        ----
            async_fn: The async function to run.
            *args: Arguments to pass to the function.
            daemon: Whether the task should be a daemon task.
            name: Optional name for the task.

        Raises
        ------
            LifecycleError: If the service is not running.

        """
        if not self.is_running:
            raise LifecycleError(
                "Tasks may not be scheduled if the service is not running"
            )

        if self.is_cancelled:
            self.logger.debug(
                "%s: service is being cancelled. Not running task %s",
                self,
                name or async_fn.__name__,
            )
            return

        if name is None:
            name = getattr(async_fn, "__name__", repr(async_fn))

        self._total_task_count += 1

        if self._task_group is not None:

            async def _run_task() -> None:
                try:
                    await async_fn(*args)
                    if daemon and not self.is_cancelled:
                        raise DaemonTaskExit(f"Daemon task {name} exited")
                except anyio.get_cancelled_exc_class():
                    self.logger.debug("%s: task %s cancelled", self, name)
                    raise
                except DaemonTaskExit:
                    if not self.is_cancelled:
                        self.logger.info(
                            "%s: daemon task %s exited normally", self, name
                        )
                except Exception:
                    self.logger.exception("%s: task %s raised an exception", self, name)
                    self._errors.append(sys.exc_info())
                    self.cancel()
                    raise

            spawn_coro(self._task_group, _run_task())

    def run_daemon_task(
        self,
        async_fn: Callable[..., Awaitable[Any]],
        *args: Any,
        name: str | None = None,
    ) -> None:
        """
        Run a daemon task in the service.

        This function will start the task and restart it if it exits normally.

        Args:
        ----
            async_fn: The async function to run.
            *args: Arguments to pass to the function.
            name: Optional name for the task.

        """
        self.run_task(async_fn, *args, daemon=True, name=name)

    def run_child_service(
        self, service: ServiceAPI, daemon: bool = False, name: str | None = None
    ) -> ManagerAPI:
        """
        Run a child service.

        Args
        ----
            service: The service to run as a child.
            daemon: Whether the service should be a daemon service.
            name: Optional name for the service.

        Returns
        -------
            The manager for the child service.

        Raises
        ------
            LifecycleError: If the service is not running.

        """
        if not self.is_running:
            raise LifecycleError(
                "Child services may not be started if the service is not running"
            )

        if self.is_cancelled:
            self.logger.debug(
                "%s: service is being cancelled. Not starting child service %s",
                self,
                name or service,
            )
            return self

        if name is None:
            name = getattr(service, "__name__", repr(service))

        self._total_task_count += 1

        if self._task_group is not None:

            async def _run_task() -> None:
                try:
                    await self.run_service(service)
                    if daemon and not self.is_cancelled:
                        raise DaemonTaskExit(f"Daemon child service {name} exited")
                except anyio.get_cancelled_exc_class():
                    self.logger.debug("%s: child service %s cancelled", self, name)
                    raise
                except DaemonTaskExit:
                    if not self.is_cancelled:
                        self.logger.info(
                            "%s: daemon child service %s exited normally", self, name
                        )
                except Exception:
                    self.logger.exception(
                        "%s: child service %s raised an exception", self, name
                    )
                    self._errors.append(sys.exc_info())
                    self.cancel()
                    raise

            spawn_coro(self._task_group, _run_task())

        child_manager = AnyIOManager(service)
        return child_manager

    def run_daemon_child_service(
        self, service: ServiceAPI, name: str | None = None
    ) -> ManagerAPI:
        """
        Run a daemon child service.

        Args
        ----
            service: The service to run as a daemon child.
            name: Optional name for the service.

        Returns
        -------
            The manager for the child service.

        """
        return self.run_child_service(service, daemon=True, name=name)

    @property
    def stats(self) -> Stats:
        """
        Get statistics about the service.

        Returns
        -------
            Statistics about the service, including task counts.

        """
        total_count = max(0, self._total_task_count)
        finished_count = min(total_count, self._done_task_count)
        return Stats(
            tasks=TaskStats(total_count=total_count, finished_count=finished_count)
        )


@asynccontextmanager
async def background_anyio_service(
    service: ServiceAPI,
) -> AsyncIterator[ManagerAPI]:
    """
    Run an AnyIO-based service in the background.

    Args
    ----
        service: The service to run in the background.

    Yields
    ------
        The manager for the service.

    """
    manager = AnyIOManager(service)
    async with anyio.create_task_group() as task_group:

        async def _run_manager() -> None:
            await manager.run()

        spawn_coro(task_group, _run_manager())
        await manager.wait_started()
        try:
            yield manager
        finally:
            manager.cancel()
            await manager.wait_finished()


def background_service(
    service_fn: Callable[..., Awaitable[Any]]
) -> Callable[..., Awaitable[None]]:
    """
    Decorator to run a function as a background service.

    Args
    ----
        service_fn: The function to run as a service.

    Returns
    -------
        A function that runs the service in the background.

    """

    @wraps(service_fn)
    async def inner(*args: Any, **kwargs: Any) -> None:
        service_type = as_service(service_fn)
        service = service_type(*args, **kwargs)
        async with background_anyio_service(service):
            pass

    return inner


def spawn_coro(task_group, coro):
    # type: (TaskGroup, Any) -> None
    task_group.spawn(coro)  # type: ignore
