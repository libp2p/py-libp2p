# Copied from https://github.com/ethereum/async-service

from abc import (
    ABC,
    abstractmethod,
)
from collections.abc import (
    Hashable,
)
from typing import (
    Any,
    Optional,
)

import trio_typing

from .stats import (
    Stats,
)
from .typing import (
    AsyncFn,
)


class TaskAPI(Hashable):
    name: str
    daemon: bool
    parent: Optional["TaskWithChildrenAPI"]

    @abstractmethod
    async def run(self) -> None: ...

    @abstractmethod
    async def cancel(self) -> None: ...

    @property
    @abstractmethod
    def is_done(self) -> bool: ...

    @abstractmethod
    async def wait_done(self) -> None: ...


class TaskWithChildrenAPI(TaskAPI):
    children: set[TaskAPI]

    @abstractmethod
    def add_child(self, child: TaskAPI) -> None: ...

    @abstractmethod
    def discard_child(self, child: TaskAPI) -> None: ...


class ServiceAPI(ABC):
    _manager: "InternalManagerAPI"

    @abstractmethod
    def get_manager(self) -> "ManagerAPI":
        """
        External retrieval of the manager for this service.

        Will raise a :class:`~async_service.exceptions.LifecycleError` if the
        service does not yet have a `manager` assigned to it.
        """
        ...

    @abstractmethod
    async def run(self) -> None:
        """
        Primary entry point for all service logic.

        .. note:: This method should **not** be directly invoked by user code.

        Services may be run using the following approaches.

        .. code-block: python

            # 1. run the service in the background using a context manager
            async with run_service(service) as manager:
                # service runs inside context block
                ...
                # service cancels and stops when context exits
            # service will have fully stopped

            # 2. run the service blocking until completion
            await Manager.run_service(service)

            # 3. create manager and then run service blocking until completion
            manager = Manager(service)
            await manager.run()
        """
        ...


class ManagerAPI(ABC):
    @property
    @abstractmethod
    def is_started(self) -> bool:
        """
        Return boolean indicating if the underlying service has been started.
        """
        ...

    @property
    @abstractmethod
    def is_running(self) -> bool:
        """
        Return boolean indicating if the underlying service is actively
        running.

        A service is considered running if it has been started and
        has not yet been stopped.
        """
        ...

    @property
    @abstractmethod
    def is_cancelled(self) -> bool:
        """
        Return boolean indicating if the underlying service has been cancelled.

        This can occure externally via the `cancel()` method or internally due
        to a task crash or a crash of the actual :meth:`ServiceAPI.run` method.
        """
        ...

    @property
    @abstractmethod
    def is_finished(self) -> bool:
        """
        Return boolean indicating if the underlying service is stopped.

        A stopped service will have completed all of the background tasks.
        """
        ...

    @property
    @abstractmethod
    def did_error(self) -> bool:
        """
        Return boolean indicating if the underlying service threw an exception.
        """
        ...

    @abstractmethod
    def cancel(self) -> None:
        """
        Trigger cancellation of the service.
        """
        ...

    @abstractmethod
    async def stop(self) -> None:
        """
        Trigger cancellation of the service and wait for it to finish.
        """
        ...

    @abstractmethod
    async def wait_started(self) -> None:
        """
        Wait until the service is started.
        """
        ...

    @abstractmethod
    async def wait_finished(self) -> None:
        """
        Wait until the service is stopped.
        """
        ...

    @classmethod
    @abstractmethod
    async def run_service(cls, service: ServiceAPI) -> None:
        """
        Run a service
        """
        ...

    @abstractmethod
    async def run(self) -> None:
        """
        Run a service
        """
        ...

    @property
    @abstractmethod
    def stats(self) -> Stats:
        """
        Return a stats object with details about the service.
        """
        ...


class InternalManagerAPI(ManagerAPI):
    """
    Defines the API that the `Service.manager` property exposes.

    The InternalManagerAPI / ManagerAPI distinction is in place to ensure that
    external callers to a service do not try to use the task scheduling
    functionality as it is only designed to be used internally.
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
        """
        Run a task in the background.  If the function throws an exception it
        will trigger the service to be cancelled and be propogated.

        If `daemon == True` then the the task is expected to run indefinitely
        and will trigger cancellation if the task finishes.
        """
        ...

    @trio_typing.takes_callable_and_args
    @abstractmethod
    def run_daemon_task(
        self, async_fn: AsyncFn, *args: Any, name: str | None = None
    ) -> None:
        """
        Run a daemon task in the background.

        Equivalent to `run_task(..., daemon=True)`.
        """
        ...

    @abstractmethod
    def run_child_service(
        self, service: ServiceAPI, daemon: bool = False, name: str | None = None
    ) -> "ManagerAPI":
        """
        Run a service in the background.  If the function throws an exception it
        will trigger the parent service to be cancelled and be propogated.

        If `daemon == True` then the the service is expected to run indefinitely
        and will trigger cancellation if the service finishes.
        """
        ...

    @abstractmethod
    def run_daemon_child_service(
        self, service: ServiceAPI, name: str | None = None
    ) -> "ManagerAPI":
        """
        Run a daemon service in the background.

        Equivalent to `run_child_service(..., daemon=True)`.
        """
        ...
