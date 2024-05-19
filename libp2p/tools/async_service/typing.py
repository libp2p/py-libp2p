# Copied from https://github.com/ethereum/async-service

from types import (
    TracebackType,
)
from typing import (
    Any,
    Awaitable,
    Callable,
    Tuple,
    Type,
)

EXC_INFO = Tuple[Type[BaseException], BaseException, TracebackType]

AsyncFn = Callable[..., Awaitable[Any]]
