# Originally copied from https://github.com/ethereum/async-service
from __future__ import (
    annotations,
)

from collections.abc import (
    AsyncIterator,
    Awaitable,
    Callable,
    Coroutine,
    Iterable,
    Sequence,
)
from contextlib import (
    asynccontextmanager,
)
import functools
import sys
from typing import (
    Any,
    Optional,
    TypeVar,
    cast,
)

if sys.version_info >= (3, 11):
    from builtins import (
        ExceptionGroup,
    )
else:
    from exceptiongroup import ExceptionGroup

import trio
import trio_typing

from ._utils import (
    get_task_name,
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
from .typing import (
    EXC_INFO,
    AsyncFn,
)


class FunctionTask(BaseFunctionTask):
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
        async_fn: AsyncFn,
        async_fn_args: Sequence[Any],
    ) -> None:
        super().__init__(name, daemon, parent, async_fn, async_fn_args)

        # We use an event to manually track when the child task is "done".
        # This is because trio has no API for awaiting completion of a task.
        self._done = trio.Event()

        # Each task gets its own `CancelScope` which is how we can manually
        # control cancellation order of the task DAG
        self._cancel_scope = trio.CancelScope()  # type: ignore[call-arg]

    #
    # Trio specific API
    #
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

    #
    # Core Task API
    #
    async def run(self) -> None:
        self.trio_task = trio.lowlevel.current_task()

        try:
            with self._cancel_scope:
                await self._async_fn(*self._async_fn_args)
                if self.daemon:
                    raise DaemonTaskExit(f"Daemon task {self} exited")

                while self.children:
                    await tuple(self.children)[0].wait_done()
        finally:
            self._done.set()
            if self.parent is not None:
                self.parent.discard_child(self)

    async def cancel(self) -> None:
        for task in tuple(self.children):
            await task.cancel()
        self._cancel_scope.cancel()
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
        parent: TaskWithChildrenAPI | None,
        child_service: ServiceAPI,
    ) -> None:
        super().__init__(name, daemon, parent)

        self._child_service = child_service
        self.child_manager = TrioManager(child_service)

    async def cancel(self) -> None:
        if self.child_manager.is_started:
            await self.child_manager.stop()


class TrioManager(BaseManager):
    # A nursery for sub tasks and services.  This nursery is cancelled if the
    # service is cancelled but allowed to exit normally if the service exits.
    _task_nursery: trio_typing.Nursery

    def __init__(self, service: ServiceAPI) -> None:
        super().__init__(service)

        # events
        self._started = trio.Event()
        self._cancelled = trio.Event()
        self._finished = trio.Event()

        # locks
        self._run_lock = trio.Lock()

    #
    # System Tasks
    #
    async def _handle_cancelled(self) -> None:
        self.logger.debug("%s: _handle_cancelled waiting for cancellation", self)
        await self._cancelled.wait()
        self.logger.debug("%s: _handle_cancelled triggering task cancellation", self)

        # The `_root_tasks` changes size as each task completes itself
        # and removes itself from the set.  For this reason we iterate over a
        # copy of the set.
        for task in tuple(self._root_tasks):
            await task.cancel()

        # This finaly cancellation of the task nursery's cancel scope ensures
        # that nothing is left behind and that the service will reliably exit.
        self._task_nursery.cancel_scope.cancel()

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
                async with trio.open_nursery() as system_nursery:
                    system_nursery.start_soon(self._handle_cancelled)

                    try:
                        async with trio.open_nursery() as task_nursery:
                            self._task_nursery = task_nursery

                            self._started.set()

                            self.run_task(self._service.run, name="run")

                            # This is hack to get the task stats correct. We don't want
                            # to count the `Service.run` method as a task. This is still
                            # imperfect as it will still count as a completed task when
                            # it finishes.
                            self._total_task_count = 0

                            # ***BLOCKING HERE***
                            # The code flow will block here until the background tasks
                            # have completed or cancellation occurs.
                    except Exception:
                        # Exceptions from any tasks spawned by our service will be
                        # caught by trio and raised here, so we store them to report
                        # together with any others we have already captured.
                        self._errors.append(cast(EXC_INFO, sys.exc_info()))
                    finally:
                        system_nursery.cancel_scope.cancel()

        finally:
            # We need this inside a finally because a trio.Cancelled exception may be
            # raised here and it wouldn't be swalled by the 'except Exception' above.
            self._finished.set()
            self.logger.debug("%s: finished", self)

        # This is outside of the finally block above because we don't want to suppress
        # trio.Cancelled or ExceptionGroup exceptions coming directly from trio.
        if self.did_error:
            raise ExceptionGroup(
                "Encountered multiple Exceptions: ",
                tuple(
                    exc_value.with_traceback(exc_tb)
                    for _, exc_value, exc_tb in self._errors
                    if isinstance(exc_value, Exception)
                ),
            )

    #
    # Event API mirror
    #
    @property
    def is_started(self) -> bool:
        return self._started.is_set()

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled.is_set()

    @property
    def is_finished(self) -> bool:
        return self._finished.is_set()

    #
    # Control API
    #
    def cancel(self) -> None:
        if not self.is_started:
            raise LifecycleError("Cannot cancel as service which was never started.")
        elif not self.is_running:
            return
        else:
            self._cancelled.set()

    #
    # Wait API
    #
    async def wait_started(self) -> None:
        await self._started.wait()

    async def wait_finished(self) -> None:
        await self._finished.wait()

    def _find_parent_task(
        self, trio_task: trio.lowlevel.Task
    ) -> TaskWithChildrenAPI | None:
        """
        Find the :class:`async_service.trio.FunctionTask` instance that corresponds to
        the given :class:`trio.lowlevel.Task` instance.
        """
        for task in FunctionTask.iterate_tasks(*self._root_tasks):
            # Any task that has not had its `trio_task` set can be safely
            # skipped as those are still in the process of starting up which
            # means that they cannot be the parent task since they will not
            # have had a chance to schedule child tasks.
            if not task.has_trio_task:
                continue

            if trio_task is task.trio_task:
                return task

        else:
            # In the case that no tasks match we assume this is a new `root`
            # task and return `None` as the parent.
            return None

    def _schedule_task(self, task: TaskAPI) -> None:
        self._task_nursery.start_soon(self._run_and_manage_task, task, name=str(task))

    def run_task(
        self,
        async_fn: Callable[..., Awaitable[Any]],
        *args: Any,
        daemon: bool = False,
        name: str | None = None,
    ) -> None:
        task = FunctionTask(
            name=get_task_name(async_fn, name),
            daemon=daemon,
            parent=self._find_parent_task(trio.lowlevel.current_task()),
            async_fn=async_fn,
            async_fn_args=args,
        )

        self._common_run_task(task)

    def run_child_service(
        self, service: ServiceAPI, daemon: bool = False, name: str | None = None
    ) -> ManagerAPI:
        task = ChildServiceTask(
            name=get_task_name(service, name),
            daemon=daemon,
            parent=self._find_parent_task(trio.lowlevel.current_task()),
            child_service=service,
        )

        self._common_run_task(task)
        return task.child_manager


TFunc = TypeVar("TFunc", bound=Callable[..., Coroutine[Any, Any, Any]])


_ChannelPayload = tuple[Optional[Any], Optional[BaseException]]


async def _wait_finished(
    service: ServiceAPI,
    api_func: Callable[..., Any],
    channel: trio.abc.SendChannel[_ChannelPayload],
) -> None:
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
    @functools.wraps(func)
    async def inner(self: ServiceAPI, *args: Any, **kwargs: Any) -> Any:
        if not hasattr(self, "manager"):
            raise LifecycleError(
                f"Cannot access external API {func}.  Service {self} has not been run."
            )

        manager = self.get_manager()

        if not manager.is_running:
            raise LifecycleError(
                f"Cannot access external API {func}.  Service {self} is not running: "
            )

        channels: tuple[
            trio.abc.SendChannel[_ChannelPayload],
            trio.abc.ReceiveChannel[_ChannelPayload],
        ] = trio.open_memory_channel(0)
        send_channel, receive_channel = channels

        async with trio.open_nursery() as nursery:
            # mypy's type hints for start_soon break with this invocation.
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


@asynccontextmanager
async def background_trio_service(service: ServiceAPI) -> AsyncIterator[ManagerAPI]:
    """
    Run a service in the background.

    The service is running within the context
    block and will be properly cleaned up upon exiting the context block.
    """
    async with trio.open_nursery() as nursery:
        manager = TrioManager(service)
        nursery.start_soon(manager.run)
        await manager.wait_started()
        try:
            yield manager
        finally:
            await manager.stop()
