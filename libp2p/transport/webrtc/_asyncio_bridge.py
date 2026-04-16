"""
trio ↔ asyncio bridge for aiortc.

Runs a single asyncio event loop in a background daemon thread.  Trio code
schedules asyncio coroutines onto it via :meth:`AsyncioBridge.run_coro` and
gets back the result (or exception) through ``trio.to_thread.run_sync``.

Design constraints
------------------
- **One bridge per WebRTCTransport** — shared across all connections.
- **All aiortc calls go through run_coro()** — no direct asyncio usage elsewhere.
- **Cancellation propagates** — trio cancellation cancels the asyncio future.
- **No monkey-patching** — aiortc's public API only.

Why a background thread?
~~~~~~~~~~~~~~~~~~~~~~~~
aiortc is built entirely on asyncio.  py-libp2p is built on trio.  The two
event loops are incompatible: you cannot ``await`` an asyncio coroutine inside
trio.  The cleanest boundary is a dedicated asyncio loop in its own thread:

    trio task  ──run_coro(coro)──►  asyncio loop (background thread)
               ◄──result/error────

``trio.to_thread.run_sync`` blocks the trio task (while yielding to other trio
tasks) until the asyncio future completes.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
from typing import Any, Coroutine, TypeVar

import trio

logger = logging.getLogger(__name__)

T = TypeVar("T")


class AsyncioBridgeError(Exception):
    """Raised when the bridge is used incorrectly (not started, already stopped)."""


class AsyncioBridge:
    """
    Manages a background asyncio event loop for running aiortc coroutines.

    Usage::

        bridge = AsyncioBridge()
        await bridge.start()
        try:
            result = await bridge.run_coro(some_asyncio_coro())
        finally:
            await bridge.stop()

    Or as an async context manager::

        async with AsyncioBridge() as bridge:
            result = await bridge.run_coro(some_asyncio_coro())
    """

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._started = False
        self._stopped = False
        # Protects start/stop against concurrent trio calls
        self._lock = trio.Lock()
        # Protects _loop/_started/_stopped reads from run_coro against
        # concurrent stop() — needed because run_coro_sync is called
        # from non-trio threads (asyncio callbacks).
        self._state_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """
        Start the background asyncio event loop.

        Safe to call multiple times — subsequent calls are no-ops if already
        running.

        :raises AsyncioBridgeError: If the bridge was previously stopped.
        """
        async with self._lock:
            if self._stopped:
                raise AsyncioBridgeError(
                    "Cannot restart a stopped AsyncioBridge — create a new instance"
                )
            if self._started:
                return

            loop = asyncio.new_event_loop()
            ready = threading.Event()

            def _run_loop() -> None:
                asyncio.set_event_loop(loop)
                ready.set()
                loop.run_forever()

            thread = threading.Thread(
                target=_run_loop,
                name="asyncio-bridge",
                daemon=True,
            )
            thread.start()
            # Wait for the loop to be running before returning
            await trio.to_thread.run_sync(ready.wait)

            with self._state_lock:
                self._loop = loop
                self._thread = thread
                self._started = True
            logger.debug("AsyncioBridge started (thread=%s)", thread.name)

    async def stop(self) -> None:
        """
        Shut down the background event loop and join the thread.

        Cancels all pending asyncio tasks before stopping.  Safe to call
        multiple times — subsequent calls are no-ops.
        """
        async with self._lock:
            if not self._started or self._stopped:
                return

            loop = self._loop
            thread = self._thread
            assert loop is not None
            assert thread is not None

            with self._state_lock:
                self._stopped = True

            # Cancel all remaining tasks on the asyncio loop
            async def _cancel_all() -> None:
                tasks = [
                    t
                    for t in asyncio.all_tasks(loop)
                    if not t.done() and t is not asyncio.current_task()
                ]
                for task in tasks:
                    task.cancel()
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)

            try:
                future = asyncio.run_coroutine_threadsafe(_cancel_all(), loop)
                await trio.to_thread.run_sync(lambda: future.result(timeout=5.0))
            except Exception:
                logger.debug("Error during task cancellation", exc_info=True)

            loop.call_soon_threadsafe(
                lambda: loop.stop()
            )  # pyrefly: ignore[bad-argument-type]

            def _join_thread() -> None:
                assert thread is not None  # narrowing for pyrefly
                thread.join(timeout=5.0)
                if thread.is_alive():
                    logger.warning("AsyncioBridge thread did not stop within timeout")

            await trio.to_thread.run_sync(_join_thread)

            with self._state_lock:
                self._loop = None
                self._thread = None
            logger.debug("AsyncioBridge stopped")

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    async def run_coro(self, coro: Coroutine[Any, Any, T]) -> T:
        """
        Schedule an asyncio coroutine on the background loop and return its
        result to the calling trio task.

        :param coro: An asyncio coroutine (not yet awaited).
        :returns: The coroutine's return value.
        :raises AsyncioBridgeError: If the bridge is not running.
        :raises Exception: Any exception raised by the coroutine is re-raised
            in the trio task.
        """
        with self._state_lock:
            loop = self._loop
            running = self._started and not self._stopped
        if loop is None or not running:
            coro.close()
            raise AsyncioBridgeError("AsyncioBridge is not running")

        future = asyncio.run_coroutine_threadsafe(coro, loop)

        def _wait_for_result() -> T:
            return future.result()

        try:
            # abandon_on_cancel=True lets trio cancel the scope immediately.
            # The background thread is abandoned but we cancel the asyncio
            # future below so it doesn't leak.  The keyword is supported at
            # runtime by trio>=0.22 even though the stubs don't declare it.
            return await trio.to_thread.run_sync(  # type: ignore[call-arg]
                _wait_for_result, abandon_on_cancel=True
            )
        except trio.Cancelled:
            # Trio scope was cancelled — propagate to the asyncio side
            future.cancel()
            raise

    def run_coro_sync(self, coro: Coroutine[Any, Any, T]) -> T:
        """
        Schedule an asyncio coroutine from a synchronous (non-trio) context.

        Useful for callbacks invoked by aiortc from the asyncio thread that
        need to schedule additional asyncio work.

        :param coro: An asyncio coroutine.
        :returns: The coroutine's return value.
        :raises AsyncioBridgeError: If the bridge is not running.
        """
        with self._state_lock:
            loop = self._loop
            running = self._started and not self._stopped
        if loop is None or not running:
            coro.close()
            raise AsyncioBridgeError("AsyncioBridge is not running")

        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result()

    def schedule_fire_and_forget(self, coro: Coroutine[Any, Any, Any]) -> None:
        """
        Schedule an asyncio coroutine without waiting for the result.

        Exceptions are logged but not raised.  Useful for cleanup tasks
        or event-driven callbacks from aiortc.

        :param coro: An asyncio coroutine.
        """
        with self._state_lock:
            loop = self._loop
            running = self._started and not self._stopped
        if loop is None or not running:
            coro.close()
            return

        def _done_callback(fut: concurrent.futures.Future[Any]) -> None:
            exc = fut.exception()
            if exc is not None:
                logger.debug("Fire-and-forget coroutine failed: %s", exc)

        future = asyncio.run_coroutine_threadsafe(coro, loop)
        future.add_done_callback(_done_callback)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        """True if the bridge is started and not yet stopped."""
        return self._started and not self._stopped

    @property
    def loop(self) -> asyncio.AbstractEventLoop | None:
        """
        The underlying asyncio event loop, or None if not started.

        Exposed for advanced use cases (e.g. creating asyncio.Futures
        directly).  Prefer :meth:`run_coro` for normal use.
        """
        return self._loop

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> AsyncioBridge:
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object | None,
    ) -> None:
        await self.stop()

    def __repr__(self) -> str:
        if self.is_running:
            state = "running"
        elif self._stopped:
            state = "stopped"
        else:
            state = "idle"
        return f"<AsyncioBridge state={state}>"
