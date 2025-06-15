# Copied from https://github.com/ethereum/async-service

from collections.abc import (
    Awaitable,
    Callable,
)
from types import (
    TracebackType,
)
from typing import (
    Any,
)

EXC_INFO = tuple[type[BaseException], BaseException, TracebackType]

AsyncFn = Callable[..., Awaitable[Any]]
