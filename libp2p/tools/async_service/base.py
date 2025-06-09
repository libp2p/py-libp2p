# Copied from https://github.com/ethereum/async-service

from abc import (
    abstractmethod,
)
import asyncio
from collections import (
    Counter,
)
from collections.abc import (
    Awaitable,
    Callable,
    Iterable,
    Sequence,
)
import logging
import sys
from typing import (
    Any,
    TypeVar,
    cast,
)
import uuid

from ._utils import (
    is_verbose_logging_enabled,
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
    TooManyChildrenException,
)
from .stats import (
    Stats,
    TaskStats,
)
from .typing import (
    EXC_INFO,
    AsyncFn,
)

MAX_CHILDREN_TASKS = 1000


class Service(ServiceAPI):
    def __str__(self) -> str:
        return self.__class__.__name__

    @property
    def manager(self) -> "InternalManagerAPI":
        """
        Expose the manager as a property here intead of
        :class:`async_service.abc.ServiceAPI` to ensure that anyone using
        proper type hints will not have access to this property since it isn't
        part of that API, while still allowing all subclasses of the
        :class:`async_service.base.Service` to access this property directly.
        """
        return self._manager

    def get_manager(self) -> ManagerAPI:
        try:
            return self._manager
        except AttributeError:
            raise LifecycleError(
                "Service does not have a manager assigned to it.  Are you sure "
                "it is running?"
            )


LogicFnType = Callable[..., Awaitable[Any]]


def as_service(service_fn: LogicFnType) -> type[ServiceAPI]:
    """
    Create a service out of a simple function
    """

    class _Service(Service):
        def __init__(self, *args: Any, **kwargs: Any):
            self._args = args
            self._kwargs = kwargs

        async def run(self) -> None:
            await service_fn(self.manager, *self._args, **self._kwargs)

    _Service.__name__ = service_fn.__name__
    _Service.__doc__ = service_fn.__doc__
    return _Service


class BaseTask(TaskAPI):
    def __init__(
        self, name: str, daemon: bool, parent: TaskWithChildrenAPI | None
    ) -> None:
        # meta
        self.name = name
        self.daemon = daemon

        # parent task
        self.parent = parent

        # For hashable interface.
        self._id = uuid.uuid4()

    def __hash__(self) -> int:
        return hash(self._id)

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, TaskAPI):
            return hash(self) == hash(other)
        else:
            return False

    def __str__(self) -> str:
        return f"{self.name}[daemon={self.daemon}]"


class BaseTaskWithChildren(BaseTask, TaskWithChildrenAPI):
    def __init__(
        self, name: str, daemon: bool, parent: TaskWithChildrenAPI | None
    ) -> None:
        super().__init__(name, daemon, parent)
        self.children = set()

    def add_child(self, child: TaskAPI) -> None:
        self.children.add(child)

    def discard_child(self, child: TaskAPI) -> None:
        self.children.discard(child)


T = TypeVar("T", bound="BaseFunctionTask")


class BaseFunctionTask(BaseTaskWithChildren):
    @classmethod
    def iterate_tasks(cls, *tasks: TaskAPI) -> Iterable["BaseFunctionTask"]:
        """Iterate over all tasks of this class type and their children recursively."""
        for task in tasks:
            if isinstance(task, BaseFunctionTask):
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


class BaseChildServiceTask(BaseTask):
    _child_service: ServiceAPI
    child_manager: ManagerAPI

    async def run(self) -> None:
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

    @property
    def is_done(self) -> bool:
        return self.child_manager.is_finished

    async def wait_done(self) -> None:
        if self.child_manager.is_started:
            await self.child_manager.wait_finished()


class BaseManager(InternalManagerAPI):
    logger = logging.getLogger("async_service.Manager")
    _verbose = is_verbose_logging_enabled()

    _service: ServiceAPI

    _errors: list[EXC_INFO]

    def __init__(self, service: ServiceAPI) -> None:
        if hasattr(service, "_manager"):
            raise LifecycleError("Service already has a manager.")
        else:
            service._manager = self

        self._service = service

        # errors
        self._errors = []

        # tasks
        self._root_tasks: set[TaskAPI] = set()

        # stats
        self._total_task_count = 0
        self._done_task_count = 0

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

    #
    # Event API mirror
    #
    @property
    def is_running(self) -> bool:
        return self.is_started and not self.is_finished

    @property
    def did_error(self) -> bool:
        return len(self._errors) > 0

    #
    # Control API
    #
    async def stop(self) -> None:
        self.cancel()
        await self.wait_finished()

    #
    # Wait API
    #
    def run_daemon_task(
        self,
        async_fn: Callable[..., Awaitable[Any]],
        *args: Any,
        name: str | None = None,
    ) -> None:
        self.run_task(async_fn, *args, daemon=True, name=name)

    def run_daemon_child_service(
        self, service: ServiceAPI, name: str | None = None
    ) -> ManagerAPI:
        return self.run_child_service(service, daemon=True, name=name)

    @property
    def stats(self) -> Stats:
        # The `max` call here ensures that if this is called prior to the
        # `Service.run` method starting we don't return `-1`
        total_count = max(0, self._total_task_count)

        # Since we track `Service.run` as a task, the `min` call here ensures
        # that when the service is fully done that we don't represent the
        # `Service.run` method in this count.
        finished_count = min(total_count, self._done_task_count)
        return Stats(
            tasks=TaskStats(total_count=total_count, finished_count=finished_count)
        )

    #
    # Task Management
    #
    @abstractmethod
    def _schedule_task(self, task: TaskAPI) -> None: ...

    def _common_run_task(self, task: TaskAPI) -> None:
        if not self.is_running:
            raise LifecycleError(
                "Tasks may not be scheduled if the service is not running"
            )

        if self.is_running and self.is_cancelled:
            self.logger.debug(
                "%s: service is being cancelled. Not running task %s", self, task
            )
            return

        self._add_child_task(task.parent, task)
        self._total_task_count += 1

        self._schedule_task(task)

    def _add_child_task(
        self, parent: TaskWithChildrenAPI | None, task: TaskAPI
    ) -> None:
        if parent is None:
            all_children = self._root_tasks
        else:
            all_children = parent.children

        if len(all_children) > MAX_CHILDREN_TASKS:
            task_counter = Counter(map(str, all_children))
            raise TooManyChildrenException(
                f"Tried to add more than {MAX_CHILDREN_TASKS} child tasks."
                f" Most common tasks: {task_counter.most_common(10)}"
            )

        if parent is None:
            if self._verbose:
                self.logger.debug("%s: running root task %s", self, task)
            self._root_tasks.add(task)
        else:
            if self._verbose:
                self.logger.debug("%s: %s running child task %s", self, parent, task)
            parent.add_child(task)

    async def _run_and_manage_task(self, task: TaskAPI) -> None:
        if self._verbose:
            self.logger.debug("%s: task %s running", self, task)

        try:
            try:
                await task.run()
            except DaemonTaskExit:
                if self.is_cancelled:
                    pass
                else:
                    raise
            finally:
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
        except asyncio.CancelledError:
            self.logger.debug("%s: task %s raised CancelledError.", self, task)
            raise
        except Exception as err:
            self.logger.error(
                "%s: task %s exited with error: %s",
                self,
                task,
                err,
                # Only show stacktrace if this is **not** a DaemonTaskExit error
                exc_info=not isinstance(err, DaemonTaskExit),
            )
            self._errors.append(cast(EXC_INFO, sys.exc_info()))
            self.cancel()
        else:
            if task.parent is None:
                self._root_tasks.remove(task)
            if self._verbose:
                self.logger.debug("%s: task %s exited cleanly.", self, task)
        finally:
            self._done_task_count += 1
