"""Regression tests for bounded error retention in the service managers."""

from __future__ import annotations

import sys

import pytest
import trio

from libp2p.tools.anyio_service import (
    AnyIOManager,
    Service,
    TrioManager,
)
from libp2p.tools.anyio_service.utils import MAX_COLLECTED_ERRORS


class _NoopService(Service):
    async def run(self) -> None:
        await trio.sleep_forever()


@pytest.mark.parametrize("manager_cls", [AnyIOManager, TrioManager])
def test_manager_error_collection_is_bounded(manager_cls) -> None:
    """
    A long-lived manager must not retain one traceback per failed task.

    Tracebacks keep their frame locals alive, so an unbounded history pins
    every stream/connection object reachable from those frames.
    """
    manager = manager_cls(_NoopService())

    last_exc: BaseException | None = None
    for _ in range(MAX_COLLECTED_ERRORS * 5):
        try:
            raise RuntimeError("boom")
        except RuntimeError as exc:
            last_exc = exc
            manager._record_error(sys.exc_info())

    assert len(manager._errors) == MAX_COLLECTED_ERRORS
    # The most recent error is the one kept.
    assert manager._errors[-1][1] is last_exc
