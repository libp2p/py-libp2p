"""
Abstract base classes for the anyio_service implementation.
"""

from abc import (
    abstractmethod,
)
from collections.abc import (
    Awaitable,
)
from typing import (
    Any,
    Callable,
    Optional,
    Protocol,
    runtime_checkable,
)

from .stats import (
    Stats,
)


@runtime_checkable
class ManagerAPI(Protocol):
    """
    Manager API defining the interface for service managers.
    """

    @property
    @abstractmethod
    def is_started(self) -> bool:
        """Return boolean indicating if service has been started."""
        ...

    @property
    @abstractmethod
    def is_running(self) -> bool:
        """Return boolean indicating if service is running."""
        ...

    @property
    @abstractmethod
    def is_cancelled(self) -> bool:
        """Return boolean indicating if service has been cancelled."""
        ...

    @property
    @abstractmethod
    def is_finished(self) -> bool:
        """Return boolean indicating if service has stopped."""
        ...

    @property
    @abstractmethod
    def did_error(self) -> bool:
        """Return boolean indicating if service threw an exception."""
        ...

    @abstractmethod
    def cancel(self) -> None:
        """Trigger cancellation of the service."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Trigger cancellation and wait for finish."""
        ...

    @abstractmethod
    async def wait_started(self) -> None:
        """Wait until service is started."""
        ...

    @abstractmethod
    async def wait_finished(self) -> None:
        """Wait until service is stopped."""
        ...

    @classmethod
    @abstractmethod
    async def run_service(cls, service: "ServiceAPI") -> None:
        """Run a service."""
        ...

    @abstractmethod
    async def run(self) -> None:
        """Run the service."""
        ...

    @property
    @abstractmethod
    def stats(self) -> Stats:
        """Return service stats."""
        ...


@runtime_checkable
class ServiceAPI(Protocol):
    """
    Service API defining the interface for all services.
    """

    @abstractmethod
    def get_manager(self) -> Optional[ManagerAPI]:
        """
        Get the manager for this service.
        """
        ...

    @property
    @abstractmethod
    def manager(self) -> Optional[ManagerAPI]:
        """Return the manager overseeing this service."""
        ...

    @manager.setter
    @abstractmethod
    def manager(self, value: Optional[ManagerAPI]) -> None:
        """Set the manager overseeing this service."""
        ...

    @abstractmethod
    async def run(self) -> None:
        """
        Primary entry point for service logic.
        """
        ...


@runtime_checkable
class InternalManagerAPI(ManagerAPI, Protocol):
    """
    Internal manager API with task scheduling capabilities.
    """

    @abstractmethod
    def run_task(
        self,
        async_fn: Callable[..., Awaitable[Any]],
        *args: Any,
        daemon: bool = False,
        name: str | None = None
    ) -> None:
        """Run a task in the background."""
        ...

    @abstractmethod
    def run_daemon_task(
        self,
        async_fn: Callable[..., Awaitable[Any]],
        *args: Any,
        name: str | None = None
    ) -> None:
        """Run a daemon task in the background."""
        ...

    @abstractmethod
    def run_child_service(
        self,
        service: ServiceAPI,
        daemon: bool = False,
        name: str | None = None,
    ) -> ManagerAPI:
        """Run a child service in the background."""
        ...

    @abstractmethod
    def run_daemon_child_service(
        self, service: ServiceAPI, name: str | None = None
    ) -> ManagerAPI:
        """Run a daemon child service in the background."""
        ...
