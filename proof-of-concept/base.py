"""
Base Service implementation.
"""

from collections.abc import (
    Awaitable,
)
from typing import (
    Any,
    Callable,
)

from .abc import (
    InternalManagerAPI,
    ManagerAPI,
    ServiceAPI,
)
from .exceptions import (
    LifecycleError,
)


class Service(ServiceAPI):
    """
    Base Service class that all services should inherit from.
    """

    def __str__(self) -> str:
        return self.__class__.__name__

    @property
    def manager(self) -> InternalManagerAPI:
        """
        Return the internal manager.
        """
        return self._manager

    def get_manager(self) -> ManagerAPI:
        """
        Return the manager, ensuring it exists.
        """
        try:
            return self._manager
        except AttributeError:
            raise LifecycleError(
                "Service does not have a manager assigned to it. "
                "Are you sure it is running?"
            )


def as_service(service_fn: Callable[..., Awaitable[Any]]) -> type[ServiceAPI]:
    """
    Create a service out of a simple function.
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
