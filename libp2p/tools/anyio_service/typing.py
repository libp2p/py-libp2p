from collections.abc import (
    Awaitable,
    Callable,
)
from typing import (
    Any,
    TypeVar,
)

EXC_INFO = tuple[type[BaseException], BaseException, Any]

AsyncFn = Callable[..., Awaitable[Any]]

TFunc = TypeVar("TFunc", bound=Callable[..., Awaitable[Any]]) 