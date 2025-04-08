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
    """Manager implementation using AnyIO's structured concurrency."""

    logger = logging.getLogger("async_service.AnyIOManager")

    def __init__(self, service: ServiceAPI) -> None:
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

        self._started_event = anyio.Event()
        self._finished_event = anyio.Event()

        self._task_group: TaskGroup | None = None
        self._cancel_scope: CancelScope | None = None

    def __str__(self) -> str:
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
        return self._started

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    @property
    def is_finished(self) -> bool:
        return self._finished

    @property
    def did_error(self) -> bool:
        return len(self._errors) > 0

    def cancel(self) -> None:
        if not self._cancelled and self._cancel_scope is not None:
            self._cancelled = True
            self._cancel_scope.cancel()

    async def stop(self) -> None:
        self.cancel()
        await self.wait_finished()

    async def wait_started(self) -> None:
        await self._started_event.wait()

    async def wait_finished(self) -> None:
        await self._finished_event.wait()

    async def run(self) -> None:
        """Run the service."""
        if self._task_group is not None:
            raise RuntimeError("Service already running")

        async with anyio.create_task_group() as task_group:
            self._task_group = task_group
            with anyio.CancelScope() as cancel_scope:
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
        """Run a service (satisfies ManagerAPI)."""
        manager = cls(service)
        await manager.run()

    def run_task(
        self,
        async_fn: Callable[..., Awaitable[Any]],
        *args: Any,
        daemon: bool = False,
        name: str | None = None,
    ) -> None:
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

        async def _tracked_task() -> None:
            try:
                await async_fn(*args)
                if daemon and not self.is_cancelled:
                    raise DaemonTaskExit(f"Daemon task {name} exited")
            except anyio.get_cancelled_exc_class():
                self.logger.debug("%s: task %s cancelled", self, name)
                raise
            except DaemonTaskExit:
                if not self.is_cancelled:
                    self.logger.info("%s: daemon task %s exited normally", self, name)
            except Exception:
                self.logger.exception("%s: task %s raised an exception", self, name)
                self._errors.append(sys.exc_info())
                self.cancel()
                raise

        if self._task_group is not None:
            self._task_group.start_soon(_tracked_task)

    def run_daemon_task(
        self,
        async_fn: Callable[..., Awaitable[Any]],
        *args: Any,
        name: str | None = None,
    ) -> None:
        self.run_task(async_fn, *args, daemon=True, name=name)

    def run_child_service(
        self, service: ServiceAPI, daemon: bool = False, name: str | None = None
    ) -> ManagerAPI:
        if service.get_manager() is not None:
            raise LifecycleError("Child service already has a manager")

        if name is None:
            name = str(service)

        child_manager = AnyIOManager(service)

        async def _run_child_service() -> None:
            try:
                await child_manager.run()
                if daemon and not self.is_cancelled:
                    raise DaemonTaskExit(f"Daemon child service {name} exited")
            except anyio.get_cancelled_exc_class():
                raise
            except Exception:
                if not self.is_cancelled:
                    self.logger.exception(
                        "%s: child service %s raised an exception", self, name
                    )
                    self._errors.append(sys.exc_info())
                    self.cancel()

        self.run_task(_run_child_service, name=f"ChildService:{name}")
        return child_manager

    def run_daemon_child_service(
        self, service: ServiceAPI, name: str | None = None
    ) -> ManagerAPI:
        return self.run_child_service(service, daemon=True, name=name)

    @property
    def stats(self) -> Stats:
        total_count = max(0, self._total_task_count)
        finished_count = min(total_count, self._done_task_count)
        return Stats(
            tasks=TaskStats(total_count=total_count, finished_count=finished_count)
        )


@asynccontextmanager
async def background_anyio_service(
    service: ServiceAPI,
) -> AsyncIterator[ManagerAPI]:
    """Context manager to run an AnyIO-based service in the background."""
    manager = AnyIOManager(service)
    async with anyio.create_task_group() as task_group:
        task_group.start_soon(manager.run)
        await manager.wait_started()
        try:
            yield manager
        finally:
            manager.cancel()
            await manager.wait_finished()


def background_service(
    service_fn: Callable[..., Awaitable[Any]]
) -> Callable[..., Awaitable[None]]:
    """Decorator to run a function as a background service."""

    @wraps(service_fn)
    async def inner(*args: Any, **kwargs: Any) -> None:
        service_type = as_service(service_fn)
        service = service_type(*args, **kwargs)
        async with background_anyio_service(service):
            pass

    return inner
