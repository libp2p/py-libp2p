"""Polling helpers for pubsub test synchronization."""

from __future__ import annotations

from collections.abc import Callable, Collection
from functools import partial
import inspect
import logging
from typing import TYPE_CHECKING

import trio

from tests.utils.pubsub.dummy_account_node import CRYPTO_TOPIC

if TYPE_CHECKING:
    from libp2p.abc import ISubscriptionAPI
    from libp2p.pubsub.pb import rpc_pb2
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


def _resolve_fail_msg(fail_msg: str | Callable[[], str], default: str) -> str:
    if callable(fail_msg):
        rendered = fail_msg()
        return rendered or default
    return fail_msg or default


async def wait_for_pubsub_payload(
    subscription: ISubscriptionAPI,
    expected: bytes,
    *,
    timeout: float = 10.0,
    fail_msg: str | Callable[[], str] = "",
) -> rpc_pb2.Message:
    """
    Wait until *subscription* yields a message whose ``data`` equals *expected*.

    Uses ``trio.fail_after`` only as a safety cap; returns as soon as the
    payload arrives.  On timeout or if the subscription ends first, raises
    ``AssertionError``.
    """
    try:
        with trio.fail_after(timeout):
            async for msg in subscription:
                if msg.data == expected:
                    return msg
    except trio.TooSlowError as exc:
        raise AssertionError(
            _resolve_fail_msg(
                fail_msg,
                f"Did not receive expected payload within {timeout}s",
            )
        ) from exc
    raise AssertionError(
        _resolve_fail_msg(
            fail_msg,
            "Subscription ended before expected payload arrived",
        )
    )


async def wait_for_pubsub_payloads(
    subscription: ISubscriptionAPI,
    expected: Collection[bytes],
    *,
    timeout: float = 10.0,
    fail_msg: str | Callable[[], str] = "",
) -> set[bytes]:
    """
    Wait until *subscription* has yielded every payload in *expected*.

    Extra messages are ignored.  ``trio.fail_after`` is only a safety cap.
    """
    remaining = set(expected)
    received: set[bytes] = set()
    try:
        with trio.fail_after(timeout):
            async for msg in subscription:
                if msg.data in remaining:
                    received.add(msg.data)
                    remaining.discard(msg.data)
                    if not remaining:
                        return received
    except trio.TooSlowError as exc:
        raise AssertionError(
            _resolve_fail_msg(
                fail_msg,
                f"Did not receive all expected payloads within {timeout}s. "
                f"Missing: {remaining}",
            )
        ) from exc
    raise AssertionError(
        _resolve_fail_msg(
            fail_msg,
            "Subscription ended before all expected payloads arrived. "
            f"Missing: {remaining}",
        )
    )


async def _wait_for_adjacency_edge_ready(
    nodes: tuple[DummyAccountNode, ...],
    src: int,
    tgt: int,
    topic: str,
    timeout: float,
) -> None:
    src_node = nodes[src]
    tgt_node = nodes[tgt]
    src_id = src_node.host.get_id()
    tgt_id = tgt_node.host.get_id()

    await src_node.pubsub.wait_for_peer(tgt_id, timeout=timeout)
    await tgt_node.pubsub.wait_for_peer(src_id, timeout=timeout)
    await src_node.pubsub.wait_for_subscription(tgt_id, topic, timeout=timeout)
    await tgt_node.pubsub.wait_for_subscription(src_id, topic, timeout=timeout)


async def wait_for_adjacency_ready(
    nodes: tuple[DummyAccountNode, ...],
    adjacency_map: dict[int, list[int]],
    *,
    topic: str = CRYPTO_TOPIC,
    timeout: float = 10.0,
) -> None:
    """
    Wait until pubsub peers and topic subscriptions are ready on every edge.

    For each directed edge in *adjacency_map*, blocks until both endpoints
    have pubsub streams and see each other's subscription on *topic*.
    Uses event-based ``wait_for_peer`` / ``wait_for_subscription`` instead of
    fixed sleeps.
    """
    try:
        with trio.fail_after(timeout):
            async with trio.open_nursery() as nursery:
                for src, targets in adjacency_map.items():
                    for tgt in targets:
                        nursery.start_soon(
                            partial(
                                _wait_for_adjacency_edge_ready,
                                nodes,
                                src,
                                tgt,
                                topic,
                                timeout,
                            )
                        )
    except trio.TooSlowError as exc:
        raise TimeoutError(
            f"Adjacency readiness timed out after {timeout:.2f}s "
            f"for topic {topic!r} with map {adjacency_map}"
        ) from exc


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
