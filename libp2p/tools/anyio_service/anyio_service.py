from collections.abc import (
    AsyncIterator,
    Awaitable,
    Callable,
)
from contextlib import (
    asynccontextmanager,
)
import contextvars
from functools import (
    wraps,
)
import sys
from typing import (
    Any,
    Optional,
    TypeVar,
    cast,
)

import anyio
from anyio.abc import (
    TaskGroup,
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
    ManagerAPI,
    ServiceAPI,
    TaskAPI,
    TaskWithChildrenAPI,
)
from .base import (
    BaseChildServiceTask,
    BaseFunctionTask,
    BaseManager,
)
from .exceptions import (
    DaemonTaskExit,
    LifecycleError,
)


def spawn_coro(task_group: TaskGroup, coro: Any) -> None:
    task_group.start_soon(coro)  # type: ignore[attr-defined]


class FunctionTask(BaseFunctionTask):
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
        self._done: anyio.Event = anyio.create_event()
        self._cancel_scope: Optional[anyio.CancelScope] = None

    async def run(self) -> None:
        try:
            async with anyio.create_task_group() as tg:
                self._cancel_scope = tg.cancel_scope
                try:
                    await self._async_fn(*self._async_fn_args)
                    if self.daemon:
                        raise DaemonTaskExit(f"Daemon task {self} exited")

                    while self.children:
                        await tuple(self.children)[0].wait_done()

                except BaseException as e:
                    if isinstance(e, DaemonTaskExit):
                        raise
                    raise
        finally:
            await self._done.set()
            if self.parent is not None:
                self.parent.discard_child(self)

    async def cancel(self) -> None:
        for task in tuple(self.children):
            await task.cancel()
        if self._cancel_scope is not None:
            await self._cancel_scope.cancel()
        await self.wait_done()

    @property
    def is_done(self) -> bool:
        return self._done.is_set()

    async def wait_done(self) -> None:
        await self._done.wait()


class ChildServiceTask(BaseChildServiceTask):
    def __init__(
        self,
        name: str,
        daemon: bool,
        parent: Optional[TaskWithChildrenAPI],
        child_service: ServiceAPI,
    ) -> None:
        super().__init__(name, daemon, parent)
        self._child_service = child_service
        self.child_manager = AnyioManager(child_service)

    async def run(self) -> None:
        await self.child_manager.run()

    async def cancel(self) -> None:
        await self.child_manager.stop()

    @property
    def is_done(self) -> bool:
        return self.child_manager.is_finished

    async def wait_done(self) -> None:
        await self.child_manager.wait_finished()


current_task_var: contextvars.ContextVar[
    Optional[FunctionTask]
] = contextvars.ContextVar("current_task_var", default=None)


class AnyioManager(BaseManager):
    def __init__(self, service: ServiceAPI) -> None:
        super().__init__(service)
        self._started: anyio.abc.Event = anyio.create_event()
        self._cancelled: anyio.abc.Event = anyio.create_event()
        self._finished: anyio.abc.Event = anyio.create_event()
        self._run_lock = anyio.create_lock()
        self._task_group: Optional[TaskGroup] = None

    @property
    def is_running(self) -> bool:
        return self.is_started and not self.is_finished

    @property
    def did_error(self) -> bool:
        return len(self._errors) > 0

    @property
    def is_started(self) -> bool:
        return self._started.is_set()

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled.is_set()

    @property
    def is_finished(self) -> bool:
        return self._finished.is_set()

    async def cancel(self) -> None:
        if not self.is_started:
            raise LifecycleError("Cannot cancel a service that was never started.")
        elif not self.is_running:
            return
        await self._cancelled.set()

    async def wait_started(self) -> None:
        await self._started.wait()

    async def wait_finished(self) -> None:
        await self._finished.wait()

    async def stop(self) -> None:
        if self.is_started:
            await self.cancel()
            await self.wait_finished()

    @classmethod
    async def run_service(cls, service: ServiceAPI) -> None:
        manager = cls(service)
        await manager.run()

    async def run(self) -> None:
        if self._run_lock.locked():
            raise LifecycleError("Service is already running.")
        if self.is_started:
            raise LifecycleError("Service has already started.")

        try:
            async with self._run_lock:
                async with anyio.create_task_group() as tg:
                    self._task_group = tg
                    await self._started.set()

                    spawn_coro(tg, self._handle_cancelled())
                    self.run_task(self._service.run, name="run")

                    await self._finished.wait()

        except BaseException as e:
            if not isinstance(e, DaemonTaskExit):
                self._errors.append((type(e), e, e.__traceback__))
        finally:
            await self._cleanup_tasks()
            await self._finished.set()

        if self.did_error:
            exceptions = []
            messages = []

            for exc_type, exc_value, exc_tb in self._errors:
                if isinstance(exc_value, Exception) and not isinstance(
                    exc_value, DaemonTaskExit
                ):
                    exceptions.append(exc_value.with_traceback(exc_tb))
                    messages.append(f"{exc_type.__name__}: {exc_value}")

            if len(exceptions) == 1:
                raise exceptions[0]
            elif len(exceptions) > 1 and sys.version_info >= (3, 11):
                raise ExceptionGroup("Multiple exceptions occurred", exceptions)

    async def _handle_cancelled(self) -> None:
        await self._cancelled.wait()
        await self._cleanup_tasks()

    async def _cleanup_tasks(self) -> None:
        for task in tuple(self._root_tasks):
            try:
                await task.cancel()
            except BaseException as e:
                if not isinstance(e, DaemonTaskExit):
                    self._errors.append((type(e), e, e.__traceback__))

    def _find_parent_task(self) -> Optional[TaskWithChildrenAPI]:
        return current_task_var.get()

    def _schedule_task(self, task: TaskAPI) -> None:
        if self._task_group is None:
            raise RuntimeError("Task group is not active.")
        self._root_tasks.add(task)
        spawn_coro(self._task_group, self._run_and_manage_task(task))

    def run_task(
        self,
        async_fn: Callable[..., Awaitable[Any]],
        *args: Any,
        daemon: bool = False,
        name: Optional[str] = None,
    ) -> None:
        parent = self._find_parent_task()
        task = FunctionTask(
            name=name or async_fn.__name__,
            daemon=daemon,
            parent=parent,
            async_fn=async_fn,
            async_fn_args=args,
        )
        self._common_run_task(task)

    def run_child_service(
        self, service: ServiceAPI, daemon: bool = False, name: Optional[str] = None
    ) -> ManagerAPI:
        parent = self._find_parent_task()
        task = ChildServiceTask(
            name=name or str(service),
            daemon=daemon,
            parent=parent,
            child_service=service,
        )
        self._common_run_task(task)
        return task.child_manager

    async def _run_and_manage_task(self, task: TaskAPI) -> None:
        token = current_task_var.set(task if isinstance(task, FunctionTask) else None)
        try:
            await task.run()
        except BaseException as e:
            if not isinstance(e, DaemonTaskExit):
                self._errors.append((type(e), e, e.__traceback__))
        finally:
            current_task_var.reset(token)
            self._root_tasks.discard(task)


@asynccontextmanager
async def background_anyio_service(service: ServiceAPI) -> AsyncIterator[ManagerAPI]:
    async with anyio.create_task_group() as tg:
        manager = AnyioManager(service)
        spawn_coro(tg, manager.run())
        await manager.wait_started()
        try:
            yield manager
        finally:
            if manager.is_started:
                await manager.stop()


T = TypeVar("T", bound=Callable[..., Any])


def external_api(func: T) -> T:
    @wraps(func)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        if not hasattr(self, "manager"):
            raise LifecycleError("Service has no manager")
        if not self.manager.is_running:
            raise LifecycleError("Service is not running")
        return func(self, *args, **kwargs)

    return cast(T, wrapper)
