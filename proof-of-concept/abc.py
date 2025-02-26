"""
Abstract base classes for the async_service implementation.
"""
from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable

from .stats import Stats

class ServiceAPI(ABC):
    """
    Service API defining the interface for all services.
    """
    @abstractmethod
    def get_manager(self) -> "ManagerAPI":
        """
        Get the manager for this service.
        """
        ...
    
    @abstractmethod
    async def run(self) -> None:
        """
        Primary entry point for service logic.
        """
        ...

class ManagerAPI(ABC):
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

class InternalManagerAPI(ManagerAPI):
    """
    Internal manager API with task scheduling capabilities.
    """
    @abstractmethod
    def run_task(
        self, async_fn: Callable[..., Awaitable[Any]], 
        *args: Any, 
        daemon: bool = False, 
        name: str = None
    ) -> None:
        """Run a task in the background."""
        ...
    
    @abstractmethod
    def run_daemon_task(
        self, async_fn: Callable[..., Awaitable[Any]], 
        *args: Any, 
        name: str = None
    ) -> None:
        """Run a daemon task in the background."""
        ...
    
    @abstractmethod
    def run_child_service(
        self, service: "ServiceAPI", 
        daemon: bool = False, 
        name: str = None
    ) -> ManagerAPI:
        """Run a child service in the background."""
        ...
    
    @abstractmethod
    def run_daemon_child_service(
        self, service: "ServiceAPI", 
        name: str = None
    ) -> ManagerAPI:
        """Run a daemon child service in the background."""
        ...