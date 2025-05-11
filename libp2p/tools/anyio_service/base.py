from abc import (
    abstractmethod,
)
from collections.abc import (
    Awaitable,
)
from typing import (
    Any,
    Callable,
    TypeVar,
    cast,
)

from .abc import (
    InternalManagerAPI,
    ManagerAPI,
    ServiceAPI,
)
from .exceptions import (
    LifecycleError,
)

LogicFnType = Callable[..., Awaitable[Any]]


class Service(ServiceAPI):
    def __str__(self) -> str:
        return self.__class__.__name__

    @property
    def manager(self) -> "InternalManagerAPI":
        """
        Expose the manager as a property here instead of
        :class:`anyio_service.abc.ServiceAPI` to ensure that anyone using
        proper type hints will not have access to this property since it isn't
        part of that API, while still allowing all subclasses of the
        :class:`anyio_service.base.Service` to access this property directly.
        """
        return self._manager

    def get_manager(self) -> ManagerAPI:
        try:
            return self._manager
        except AttributeError:
            raise LifecycleError(
                "Service does not have a manager assigned to it. Are you sure "
                "it is running?"
            )


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