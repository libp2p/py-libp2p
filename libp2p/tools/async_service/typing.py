# Copied from https://github.com/ethereum/async-service

from collections.abc import (
    Awaitable,
)
from types import (
    TracebackType,
)
from typing import (
    Any,
    Callable,
)

EXC_INFO = tuple[type[BaseException], BaseException, TracebackType]

AsyncFn = Callable[..., Awaitable[Any]]
