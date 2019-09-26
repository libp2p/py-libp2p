import asyncio
from typing import Any, Awaitable, Set

# Ref: https://github.com/ethereum/trinity/blob/master/p2p/service.py#L39


class Cancellable:
    _tasks: Set["asyncio.Future[Any]"]
    _is_cancelled: bool

    def __init__(self) -> None:
        self._tasks = set()
        self._is_cancelled = False

    def run_task(self, awaitable: Awaitable[Any]) -> None:
        if self._is_cancelled:
            return
        self._tasks.add(asyncio.ensure_future(awaitable))

    async def cancel(self) -> None:
        if self._is_cancelled:
            return
        self._is_cancelled = True
        for task in self._tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
