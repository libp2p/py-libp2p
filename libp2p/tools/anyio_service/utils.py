"""
Utility functions for anyio_service implementation.
"""

from collections.abc import (
    AsyncGenerator,
)
from typing import (
    Any,
    Callable,
    TypeVar,
)

import anyio

from .abc import (
    ServiceAPI,
)
from .manager import (
    AnyIOManager,
)

TFunc = TypeVar("TFunc", bound=Callable[..., Any])
TService = TypeVar("TService", bound=ServiceAPI)


class SimpleService(ServiceAPI):
    """
    A simple service implementation that wraps an async function.
    """

    def __init__(
        self, service_fn: Callable[..., Any], *args: Any, **kwargs: Any
    ) -> None:
        self._service_fn = service_fn
        self._args = args
        self._kwargs = kwargs
        self.manager: AnyIOManager | None = None

    async def run(self) -> None:
        await self._service_fn(*self._args, **self._kwargs)

    def get_manager(self) -> AnyIOManager | None:
        return self.manager


def as_service(service_fn: TFunc) -> Callable[..., SimpleService]:
    """
    Convert a regular async function into a service class.
    """

    def create_service(*args: Any, **kwargs: Any) -> SimpleService:
        return SimpleService(service_fn, *args, **kwargs)

    return create_service


def get_task_name(value: Any, explicit_name: str | None = None) -> str:
    """
    Get a name for a task or service.
    """
    if explicit_name is not None:
        return explicit_name

    if isinstance(value, ServiceAPI):
        value_cls = type(value)
        if value_cls.__str__ is not object.__str__:
            return str(value)
        if value_cls.__repr__ is not object.__repr__:
            return repr(value)
        return value_cls.__name__

    try:
        return value.__name__  # No need for type: ignore since we catch AttributeError
    except AttributeError:
        return repr(value)


async def background_anyio_service(
    service: TService,
) -> AsyncGenerator[AnyIOManager, None]:
    """Context manager to run an AnyIO-based service in the background."""
    manager = AnyIOManager(service)
    async with anyio.create_task_group() as task_group:
        task_group.start_soon(manager.run)
        await manager.wait_started()
        yield manager
    manager.cancel()
    await manager.wait_finished()
