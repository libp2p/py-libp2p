from typing import Any, List, Optional

import trio


class QueueClosed(Exception):
    pass

class QueueFull(Exception):
    pass

class QueuePushOnClosed(Exception):
    pass

class QueueCancelled(Exception):
    pass

class PriorityQueue:
    def __init__(self) -> None:
        self.normal: List[Any] = []
        self.priority: List[Any] = []

    def __len__(self) -> int:
        return len(self.normal) + len(self.priority)

    def normal_push(self, rpc: Any) -> None:
        self.normal.append(rpc)

    def priority_push(self, rpc: Any) -> None:
        self.priority.append(rpc)

    def pop(self) -> Optional[Any]:
        if self.priority:
            return self.priority.pop(0)
        elif self.normal:
            return self.normal.pop(0)
        return None

class RpcQueue:
    def __init__(self, max_size: int) -> None:
        self.queue: PriorityQueue = PriorityQueue()
        self.max_size: int = max_size
        self.closed: bool = False
        self._lock = trio.Lock()
        self._space_available = trio.Condition(self._lock)

    async def push(self, rpc: Any, block: bool = True) -> None:
        await self._push(rpc, urgent=False, block=block)

    async def urgent_push(self, rpc: Any, block: bool = True) -> None:
        await self._push(rpc, urgent=True, block=block)

    async def _push(self, rpc: Any, urgent: bool, block: bool) -> None:
        async with self._lock:
            if self.closed:
                raise QueuePushOnClosed("push on closed rpc queue")
            while len(self.queue) == self.max_size:
                if block:
                    await self._space_available.wait()
                    if self.closed:
                        raise QueuePushOnClosed("push on closed rpc queue")
                else:
                    raise QueueFull("rpc queue full")
            if urgent:
                self.queue.priority_push(rpc)
            else:
                self.queue.normal_push(rpc)
            self._space_available.notify()

    async def pop(self) -> Any:
        while True:
            async with self._lock:
                if self.closed:
                    raise QueueClosed("rpc queue closed")
                if len(self.queue) > 0:
                    rpc = self.queue.pop()
                    self._space_available.notify()
                    return rpc
                # If queue is empty, wait for a message or closure
                await self._space_available.wait()
                if self.closed:
                    raise QueueClosed("rpc queue closed")

    async def close(self) -> None:
        async with self._lock:
            self.closed = True
            self._space_available.notify_all()
