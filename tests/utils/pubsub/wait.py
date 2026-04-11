"""Polling helpers for pubsub test synchronization."""

from __future__ import annotations

from collections.abc import Callable
import inspect
import logging
from typing import TYPE_CHECKING

import trio

if TYPE_CHECKING:
    from tests.utils.pubsub.dummy_account_node import DummyAccountNode

logger = logging.getLogger(__name__)


async def wait_for(
    predicate: Callable[[], object],
    *,
    timeout: float = 10.0,
    poll_interval: float = 0.02,
    fail_msg: str = "",
) -> None:
    """
    Poll until *predicate()* returns a truthy value, or raise ``TimeoutError``.

    Supports sync predicates, async predicates, and callables that return
    awaitables (e.g. ``lambda: some_async_fn()``).  If the predicate raises
    an exception it is treated as falsy; on timeout the last such exception
    is chained to the ``TimeoutError``.
    """
    start = trio.current_time()
    last_exc: Exception | None = None

    while True:
        try:
            result = predicate()
            if inspect.isawaitable(result):
                result = await result
            if result:
                return
        except Exception as exc:
            last_exc = exc

        elapsed = trio.current_time() - start
        if elapsed > timeout:
            msg = fail_msg or f"wait_for timed out after {elapsed:.2f}s"
            err = TimeoutError(msg)
            if last_exc is not None:
                raise err from last_exc
            raise err

        await trio.sleep(poll_interval)


async def wait_for_convergence(
    nodes: tuple[DummyAccountNode, ...],
    check: Callable[[DummyAccountNode], bool],
    timeout: float = 10.0,
    poll_interval: float = 0.02,
    log_success: bool = False,
    raise_last_exception_on_timeout: bool = True,
) -> None:
    """
    Wait until all *nodes* satisfy *check*.

    Returns as soon as convergence is reached, otherwise raises
    ``TimeoutError`` (or ``AssertionError`` when
    *raise_last_exception_on_timeout* is ``True`` and a node raised).

    Preserves the API of the original inline helper from
    ``test_dummyaccount_demo.py``.
    """
    start_time = trio.current_time()

    last_exception: Exception | None = None
    last_exception_node: int | None = None

    while True:
        failed_indices: list[int] = []
        for i, node in enumerate(nodes):
            try:
                ok = check(node)
            except Exception as exc:
                ok = False
                last_exception = exc
                last_exception_node = i
            if not ok:
                failed_indices.append(i)

        if not failed_indices:
            elapsed = trio.current_time() - start_time
            if log_success:
                logger.debug("Converged in %.3fs with %d nodes", elapsed, len(nodes))
            return

        elapsed = trio.current_time() - start_time
        if elapsed > timeout:
            if raise_last_exception_on_timeout and last_exception is not None:
                node_hint = (
                    f" (node index {last_exception_node})"
                    if last_exception_node is not None
                    else ""
                )
                raise AssertionError(
                    f"Convergence failed{node_hint}: {last_exception}"
                ) from last_exception

            raise TimeoutError(
                f"Convergence timeout after {elapsed:.2f}s. "
                f"Failed nodes: {failed_indices}. "
                f"(Hint: run with -s and pass log_success=True for timing logs)"
            )

        await trio.sleep(poll_interval)
