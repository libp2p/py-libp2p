import anyio
import logging
import sys
from collections.abc import (
    Awaitable,
    Callable,
)
from contextlib import (
    asynccontextmanager,
)
from functools import (
    wraps,
)
from typing import (
    Any,
    AsyncIterator,
    Optional,
    TypeVar,
    cast,
    Union,
)

if sys.version_info >= (3, 11):
    from builtins import (
        ExceptionGroup,
    )
else:
    from exceptiongroup import (
        ExceptionGroup,
    )

from .abc import (
    InternalManagerAPI,
    ManagerAPI,
    ServiceAPI,
    TaskAPI,
    TaskWithChildrenAPI,
)
from .exceptions import (
    DaemonTaskExit,
    LifecycleError,
)
from .stats import (
    Stats,
    TaskStats,
)
from .typing import (
    EXC_INFO,
)

logger = logging.getLogger("anyio_service.Manager")

T = TypeVar("T", bound=Callable[..., Any])

def external_api(func: T) -> T:
    """
    Decorator to mark a method as an external API that can be called from outside the service.
    This ensures that the service is in the correct state before allowing the method to be called.
    """
    @wraps(func)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        if not hasattr(self, "manager"):
            raise LifecycleError("Service has no manager")
        if not self.manager.is_running:
            raise LifecycleError("Service is not running")
        return func(self, *args, **kwargs)
    return cast(T, wrapper)


class BaseTask(TaskAPI):
    def __init__(
        self,
        name: str,
        daemon: bool,
        parent: Optional[TaskWithChildrenAPI],
    ) -> None:
        self.name = name
        self.daemon = daemon
        self.parent = parent
        self.children: set[TaskAPI] = set()

    def __str__(self) -> str:
        return self.name

    def __hash__(self) -> int:
        return id(self)

    def __eq__(self, other: Any) -> bool:
        return self is other


class FunctionTask(BaseTask):
    def __init__(
        self,
        name: str,
        daemon: bool,
        parent: Optional[TaskWithChildrenAPI],
        async_fn: Callable[..., Awaitable[Any]],
        async_fn_args: tuple[Any, ...],
    ) -> None:
        super().__init__(name, daemon, parent)
        self._async_fn = async_fn
        self._async_fn_args = async_fn_args
        self._done = anyio.Event()
        self._cancel_scope: Optional[anyio.CancelScope] = None

    async def run(self) -> None:
        try:
            async with anyio.create_task_group() as tg:
                self._cancel_scope = tg.cancel_scope
                try:
                    await self._async_fn(*self._async_fn_args)
                    if self.daemon:
                        raise DaemonTaskExit(f"Daemon task {self} exited")
                except BaseException as e:
                    if isinstance(e, DaemonTaskExit):
                        raise
                    raise
        finally:
            self._done.set()
            if self.parent is not None:
                self.parent.discard_child(self)

    async def cancel(self) -> None:
        if self._cancel_scope is not None:
            self._cancel_scope.cancel()
        await self.wait_done()

    @property
    def is_done(self) -> bool:
        return self._done.is_set()

    async def wait_done(self) -> None:
        await self._done.wait()


class ChildServiceTask(BaseTask):
    def __init__(
        self,
        name: str,
        daemon: bool,
        parent: Optional[TaskWithChildrenAPI],
        child_service: ServiceAPI,
    ) -> None:
        super().__init__(name, daemon, parent)
        self.child_service = child_service
        self.child_manager = AnyioManager(child_service)
        self._done = anyio.Event()
        self._cancel_scope: Optional[anyio.CancelScope] = None

    async def run(self) -> None:
        if self.child_manager.is_started:
            raise LifecycleError(
                f"Child service {self.child_service} has already been started"
            )

        try:
            async with anyio.create_task_group() as tg:
                self._cancel_scope = tg.cancel_scope
                try:
                    await self.child_manager.run()
                    if self.daemon:
                        raise DaemonTaskExit(f"Daemon task {self} exited")
                except BaseException as e:
                    if isinstance(e, DaemonTaskExit):
                        raise
                    raise
        finally:
            self._done.set()
            if self.parent is not None:
                self.parent.discard_child(self)

    async def cancel(self) -> None:
        try:
            if self.child_manager.is_started:
                await self.child_manager.stop()
        finally:
            if self._cancel_scope is not None:
                self._cancel_scope.cancel()
            self._done.set()
            if self.parent is not None:
                self.parent.discard_child(self)

    @property
    def is_done(self) -> bool:
        return self._done.is_set() and self.child_manager.is_finished

    async def wait_done(self) -> None:
        if self.child_manager.is_started:
            await self.child_manager.wait_finished()
        await self._done.wait()


class AnyioManager(InternalManagerAPI):
    def __init__(self, service: ServiceAPI) -> None:
        if hasattr(service, "_manager"):
            raise LifecycleError("Service already has a manager.")
        else:
            service._manager = self

        self._service = service
        self._errors: list[EXC_INFO] = []
        self._root_tasks: set[TaskAPI] = set()
        self._total_task_count = 0
        self._done_task_count = 0

        self._started = anyio.Event()
        self._cancelled = anyio.Event()
        self._finished = anyio.Event()

        self._run_lock = anyio.Lock()
        self._task_group: Optional[anyio.abc.TaskGroup] = None

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
        return f"<Manager[{self._service}] flags={status_flags}>"

    @property
    def is_running(self) -> bool:
        return self.is_started and not self.is_finished

    @property
    def did_error(self) -> bool:
        return len(self._errors) > 0

    async def stop(self) -> None:
        """Stop the service and wait for it to finish."""
        if self.is_started:
            self.cancel()
            await self.wait_finished()

    def run_daemon_task(
        self, async_fn: Callable[..., Awaitable[Any]], *args: Any, name: Optional[str] = None
    ) -> None:
        self.run_task(async_fn, *args, daemon=True, name=name)

    def run_daemon_child_service(
        self, service: ServiceAPI, name: Optional[str] = None
    ) -> ManagerAPI:
        return self.run_child_service(service, daemon=True, name=name)

    @property
    def stats(self) -> Stats:
        total_count = max(0, self._total_task_count)
        finished_count = min(total_count, self._done_task_count)
        return Stats(
            tasks=TaskStats(total_count=total_count, finished_count=finished_count)
        )

    def _add_child_task(self, parent: Optional[TaskWithChildrenAPI], task: TaskAPI) -> None:
        if parent is not None:
            parent.add_child(task)

    def _common_run_task(self, task: TaskAPI) -> None:
        if not self.is_running:
            raise LifecycleError(
                "Tasks may not be scheduled if the service is not running"
            )

        if self.is_running and self.is_cancelled:
            logger.debug(
                "%s: service is being cancelled. Not running task %s", self, task
            )
            return

        self._add_child_task(task.parent, task)
        self._total_task_count += 1
        self._schedule_task(task)

    def _schedule_task(self, task: TaskAPI) -> None:
        if self._task_group is None:
            raise RuntimeError("Cannot schedule task: TaskGroup is not active")
        self._root_tasks.add(task)
        self._task_group.start_soon(self._run_and_manage_task, task)

    async def _run_and_manage_task(self, task: TaskAPI) -> None:
        try:
            await task.run()
        except BaseException as e:
            if isinstance(e, DaemonTaskExit):
                # Re-raise DaemonTaskExit directly
                raise
            # Store the original exception
            self._errors.append((type(e), e, e.__traceback__))
            self.cancel()
        finally:
            self._root_tasks.discard(task)
            self._done_task_count += 1

        # Handle ExceptionGroup if multiple exceptions occurred
        if len(self._errors) > 1:
            exceptions = [exc_value.with_traceback(exc_tb) for exc_type, exc_value, exc_tb in self._errors]
            if sys.version_info >= (3, 11):
                raise ExceptionGroup("Multiple exceptions occurred", exceptions)
            else:
                raise RuntimeError("; ".join(f"{exc_type.__name__}: {str(exc_value)}" for exc_type, exc_value, exc_tb in self._errors))

    @classmethod
    async def run_service(cls, service: ServiceAPI) -> None:
        manager = cls(service)
        await manager.run()

    async def run(self) -> None:
        if self._run_lock.locked():
            raise LifecycleError(
                "Cannot run a service with the run lock already engaged. "
                "Already started?"
            )
        elif self.is_started:
            raise LifecycleError("Cannot run a service which is already started.")

        try:
            async with self._run_lock:
                async with anyio.create_task_group() as tg:
                    self._task_group = tg
                    tg.start_soon(self._handle_cancelled)

                    try:
                        self._started.set()
                        self.run_task(self._service.run, name="run")
                        await self._finished.wait()
                    except BaseException as e:
                        if not isinstance(e, DaemonTaskExit):
                            self._errors.append((type(e), e, e.__traceback__))
                    finally:
                        # Ensure all tasks are cancelled
                        tg.cancel_scope.cancel()
                        await self._cleanup_tasks()

        finally:
            logger.debug("%s: finished", self)
            self._finished.set()

        if self.did_error:
            exceptions = []
            error_messages = []
            for exc_type, exc_value, exc_tb in self._errors:
                if isinstance(exc_value, Exception):
                    if not isinstance(exc_value, DaemonTaskExit):
                        exceptions.append(exc_value.with_traceback(exc_tb))
                        error_messages.append(f"{exc_type.__name__}: {str(exc_value)}")
            
            if len(exceptions) == 1:
                raise exceptions[0]
            elif len(exceptions) > 1:
                # Format the error message consistently
                error_msg = "; ".join(error_messages)
                if sys.version_info >= (3, 11):
                    raise ExceptionGroup("Multiple exceptions occurred", exceptions)
                else:
                    raise RuntimeError(error_msg)

    async def _cleanup_tasks(self) -> None:
        """Clean up any remaining tasks."""
        for task in tuple(self._root_tasks):
            try:
                await task.cancel()
            except BaseException as e:
                if not isinstance(e, DaemonTaskExit):
                    self._errors.append((type(e), e, e.__traceback__))
        self._finished.set()

    async def _handle_cancelled(self) -> None:
        """Handle service cancellation."""
        logger.debug("%s: _handle_cancelled waiting for cancellation", self)
        await self._cancelled.wait()
        logger.debug("%s: _handle_cancelled triggering task cancellation", self)
        await self._cleanup_tasks()

    @property
    def is_started(self) -> bool:
        return self._started.is_set()

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled.is_set()

    @property
    def is_finished(self) -> bool:
        return self._finished.is_set()

    def cancel(self) -> None:
        if not self.is_started:
            raise LifecycleError("Cannot cancel a service that was never started.")
        elif not self.is_running:
            return
        else:
            self._cancelled.set()

    async def wait_started(self) -> None:
        await self._started.wait()

    async def wait_finished(self) -> None:
        await self._finished.wait()

    def run_task(
        self,
        async_fn: Callable[..., Awaitable[Any]],
        *args: Any,
        daemon: bool = False,
        name: Optional[str] = None,
    ) -> None:
        task = FunctionTask(
            name=name or async_fn.__name__,
            daemon=daemon,
            parent=None,
            async_fn=async_fn,
            async_fn_args=args,
        )
        self._common_run_task(task)

    def run_child_service(
        self, service: ServiceAPI, daemon: bool = False, name: Optional[str] = None
    ) -> ManagerAPI:
        task = ChildServiceTask(
            name=name or str(service),
            daemon=daemon,
            parent=None,
            child_service=service,
        )
        self._common_run_task(task)
        return task.child_manager


@asynccontextmanager
async def background_anyio_service(service: ServiceAPI) -> AsyncIterator[ManagerAPI]:
    """Run a service in the background and yield its manager.
    
    The service will be stopped when the context exits.
    """
    async with anyio.create_task_group() as tg:
        manager = AnyioManager(service)
        tg.start_soon(manager.run)
        await manager.wait_started()
        try:
            yield manager
        finally:
            if manager.is_started:
                await manager.stop()
