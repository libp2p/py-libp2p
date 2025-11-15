"""Public Service API layer with decorators and helper functions."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Coroutine
import functools
import sys
from typing import Any, Optional, TypeVar, cast

import anyio
from anyio.abc import ObjectReceiveStream, ObjectSendStream

from .exceptions import LifecycleError
from .stats import Stats

__all__ = [
    "AsyncFn",
    "ManagerAPI",
    "InternalManagerAPI",
    "ServiceAPI",
    "Service",
    "as_service",
    "external_api",
]

# Type aliases
AsyncFn = Callable[..., Awaitable[Any]]
TFunc = TypeVar("TFunc", bound=Callable[..., Coroutine[Any, Any, Any]])


# ============================================================================
# Core API Abstractions
# ============================================================================


class ManagerAPI(ABC):
    """External interface for service managers."""

    @property
    @abstractmethod
    def is_started(self) -> bool:
        """Return True if the service has been started."""
        ...

    @property
    @abstractmethod
    def is_running(self) -> bool:
        """Return True if the service is actively running."""
        ...

    @property
    @abstractmethod
    def is_cancelled(self) -> bool:
        """Return True if the service has been cancelled."""
        ...

    @property
    @abstractmethod
    def is_finished(self) -> bool:
        """Return True if the service has finished."""
        ...

    @property
    @abstractmethod
    def did_error(self) -> bool:
        """Return True if the service encountered an error."""
        ...

    @abstractmethod
    async def wait_started(self) -> None:
        """Wait for the service to start."""
        ...

    @abstractmethod
    async def wait_finished(self) -> None:
        """Wait for the service to finish."""
        ...

    @abstractmethod
    def cancel(self) -> None:
        """Cancel the service (non-blocking)."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Stop the service and wait for completion."""
        ...

    @property
    @abstractmethod
    def stats(self) -> Stats:
        """Get service statistics."""
        ...


class InternalManagerAPI(ManagerAPI):
    """
    Internal interface for service managers with task scheduling capabilities.

    This extends ManagerAPI with methods that should only be used internally
    by the service implementation, not by external callers.
    """

    @abstractmethod
    def run_task(
        self,
        async_fn: AsyncFn,
        *args: Any,
        daemon: bool = False,
        name: str | None = None,
    ) -> None:
        """Run a task in the background."""
        ...

    @abstractmethod
    def run_daemon_task(
        self, async_fn: AsyncFn, *args: Any, name: str | None = None
    ) -> None:
        """Run a daemon task (expected to run indefinitely)."""
        ...

    @abstractmethod
    def run_child_service(
        self, service: ServiceAPI, daemon: bool = False, name: str | None = None
    ) -> ManagerAPI:
        """Run a child service in the background."""
        ...

    @abstractmethod
    def run_daemon_child_service(
        self, service: ServiceAPI, name: str | None = None
    ) -> ManagerAPI:
        """Run a daemon child service."""
        ...


class ServiceAPI(ABC):
    """Abstract base class for services."""

    _manager: InternalManagerAPI

    @abstractmethod
    def get_manager(self) -> ManagerAPI:
        """Get the manager for this service."""
        ...

    @abstractmethod
    async def run(self) -> None:
        """Main service logic - implemented by subclasses."""
        ...


# ============================================================================
# Service Implementation
# ============================================================================


class Service(ServiceAPI):
    """AnyIO-based service implementation."""

    def __str__(self) -> str:
        return self.__class__.__name__

    @property
    def manager(self) -> InternalManagerAPI:
        """Internal access to the manager (for subclasses)."""
        return self._manager

    def get_manager(self) -> ManagerAPI:
        """External access to the manager."""
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
    """Convert a simple async function into a Service class."""

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
    stream: ObjectSendStream[_ChannelPayload],
) -> None:
    """Helper for external_api: wait for service to finish."""
    manager = service.get_manager()

    if manager.is_finished:
        await stream.send(
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
    await stream.send(
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
    stream: ObjectSendStream[_ChannelPayload],
) -> None:
    """Helper for external_api: execute the API function."""
    try:
        result = await api_fn(self, *args, **kwargs)
    except Exception:
        _, exc_value, exc_tb = sys.exc_info()
        if exc_value is None or exc_tb is None:
            raise Exception(
                "This should be unreachable but acts as a type guard for mypy"
            )
        await stream.send((None, exc_value.with_traceback(exc_tb)))
    else:
        await stream.send((result, None))


def external_api(func: TFunc) -> TFunc:
    """
    Decorator to protect external API methods.

    MEDIUM COMPLEXITY: Ensures methods can only be called while service is running.
    Uses AnyIO streams and task groups to race the API call against service shutdown.
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

        # Create a memory stream for communication
        streams: tuple[
            ObjectSendStream[_ChannelPayload],
            ObjectReceiveStream[_ChannelPayload],
        ] = anyio.create_memory_object_stream(0)
        send_stream, receive_stream = streams

        # Race the API call against service finishing
        async with anyio.create_task_group() as tg:
            tg.start_soon(
                _wait_api_fn,  # type: ignore
                self,
                func,
                args,
                kwargs,
                send_stream,
            )
            tg.start_soon(_wait_finished, self, func, send_stream)
            result, err = await receive_stream.receive()
            tg.cancel_scope.cancel()

        if err is None:
            return result
        else:
            raise err

    return cast(TFunc, inner)
