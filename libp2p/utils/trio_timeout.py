from collections.abc import Awaitable
from typing import Any

import trio


async def with_timeout(
    awaitable: Awaitable[Any],
    timeout: float | None,
    err_msg: str,
    err_type: type[BaseException],
) -> Any:
    try:
        if timeout is not None:
            with trio.fail_after(timeout):
                return await awaitable
        return await awaitable
    except trio.TooSlowError:
        raise err_type(err_msg) from None
