import threading
from typing import Any, List, Optional

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
        self.queue_mu: threading.Lock = threading.Lock()
        self.space_available: threading.Condition = threading.Condition(self.queue_mu)

    def push(self, rpc: Any, block: bool = True) -> None:
        return self._push(rpc, urgent=False, block=block)

    def urgent_push(self, rpc: Any, block: bool = True) -> None:
        return self._push(rpc, urgent=True, block=block)

    def _push(self, rpc: Any, urgent: bool, block: bool) -> None:
        with self.queue_mu:
            if self.closed:
                raise QueuePushOnClosed("push on closed rpc queue")
            while len(self.queue) == self.max_size:
                if block:
                    self.space_available.wait()
                    if self.closed:
                        raise QueuePushOnClosed("push on closed rpc queue")
                else:
                    raise QueueFull("rpc queue full")
            if urgent:
                self.queue.priority_push(rpc)
            else:
                self.queue.normal_push(rpc)
            self.space_available.notify()

    def pop(self) -> Any:
        with self.queue_mu:
            if self.closed:
                raise QueueClosed("rpc queue closed")
            while len(self.queue) == 0:
                self.space_available.wait()
            rpc = self.queue.pop()
            self.space_available.notify()
            return rpc

    def close(self) -> None:
        with self.queue_mu:
            self.closed = True
            self.space_available.notify_all()
