from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import trio


class ReadWriteLock:
    """
    A read-write lock that allows multiple concurrent readers
    or one exclusive writer, implemented using Trio primitives.
    """

    def __init__(self) -> None:
        self._readers = 0
        self._readers_lock = trio.Lock()  # Protects access to _readers count
        self._writer_lock = trio.Semaphore(1)  # Allows only one writer at a time

    async def acquire_read(self) -> None:
        """Acquire a read lock. Multiple readers can hold it simultaneously."""
        try:
            async with self._readers_lock:
                if self._readers == 0:
                    await self._writer_lock.acquire()
                self._readers += 1
        except trio.Cancelled:
            raise

    async def release_read(self) -> None:
        """Release a read lock."""
        async with self._readers_lock:
            if self._readers == 1:
                self._writer_lock.release()
            self._readers -= 1

    async def acquire_write(self) -> None:
        """Acquire an exclusive write lock."""
        try:
            await self._writer_lock.acquire()
        except trio.Cancelled:
            raise

    def release_write(self) -> None:
        """Release the exclusive write lock."""
        self._writer_lock.release()

    @asynccontextmanager
    async def read_lock(self) -> AsyncGenerator[None, None]:
        """Context manager for acquiring and releasing a read lock safely."""
        acquire = False
        try:
            await self.acquire_read()
            acquire = True
            yield
        finally:
            if acquire:
                with trio.CancelScope() as scope:
                    scope.shield = True
                    await self.release_read()

    @asynccontextmanager
    async def write_lock(self) -> AsyncGenerator[None, None]:
        """Context manager for acquiring and releasing a write lock safely."""
        acquire = False
        try:
            await self.acquire_write()
            acquire = True
            yield
        finally:
            if acquire:
                self.release_write()
