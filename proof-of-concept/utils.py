"""
Utility functions for async_service implementation.
"""

from typing import (
    Any,
    Callable,
    TypeVar,
    cast,
)

from .abc import (
    ServiceAPI,
)


class SimpleService:
    """
    A simple service implementation that wraps an async function.
    """

    def __init__(self, service_fn, *args, **kwargs):
        self._service_fn = service_fn
        self._args = args
        self._kwargs = kwargs

    async def run(self) -> None:
        await self._service_fn(*self._args, **self._kwargs)


TFunc = TypeVar("TFunc", bound=Callable[..., Any])
TService = TypeVar("TService", bound=ServiceAPI)


def as_service(service_fn: TFunc) -> Callable[..., TService]:
    """
    Convert a regular async function into a service class.
    """

    def create_service(*args: Any, **kwargs: Any) -> TService:
        return cast(TService, SimpleService(service_fn, *args, **kwargs))

    return create_service


def get_task_name(value: Any, explicit_name: str = None) -> str:
    """
    Get a name for a task or service.
    """
    if explicit_name is not None:
        # if an explicit name was provided, just return that.
        return explicit_name

    # Import here to avoid circular imports
    from .abc import (
        ServiceAPI,
    )

    if isinstance(value, ServiceAPI):
        # Service instance naming rules:
        #
        # 1. str if the class implements a custom str method
        # 2. repr if the class implements a custom repr method
        # 3. The Service class name.
        value_cls = type(value)
        if value_cls.__str__ is not object.__str__:
            return str(value)
        if value_cls.__repr__ is not object.__repr__:
            return repr(value)
        else:
            return value_cls.__name__
    else:
        try:
            # Prefer the name of the function if it has one
            return str(value.__name__)
        except AttributeError:
            return repr(value)
