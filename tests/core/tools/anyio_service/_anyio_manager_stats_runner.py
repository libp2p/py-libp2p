"""
Standalone runner for anyio manager stats tests.

Runs in a subprocess so the test has a single, clean Trio run. Avoids
pytest-xdist worker reuse (nested trio.run) and timeout under xdist.

Usage:
    python -m tests.core.tools.anyio_service._anyio_manager_stats_runner TEST_NAME
"""

from __future__ import annotations

import sys

import anyio

from libp2p.tools.anyio_service import (
    AnyIOManager,
    Service,
)


async def checkpoint() -> None:
    """AnyIO checkpoint helper for tests."""
    await anyio.sleep(0)


async def _run_test_anyio_manager_stats() -> None:
    ready = anyio.Event()

    class StatsTest(Service):
        async def run(self) -> None:
            self.manager.run_task(anyio.sleep_forever)
            self.manager.run_task(anyio.sleep_forever)
            self.manager.run_task(checkpoint)
            self.manager.run_task(checkpoint)
            self.manager.run_task(self.run_with_children, 4)

        async def run_with_children(self, num_children: int) -> None:
            for _ in range(num_children):
                self.manager.run_task(anyio.sleep_forever)
            ready.set()

        def run_external_root(self) -> None:
            self.manager.run_task(checkpoint)

    service = StatsTest()
    async with anyio.create_task_group() as tg:
        manager = AnyIOManager(service)
        tg.start_soon(manager.run)  # type: ignore[arg-type]
        await manager.wait_started()

        try:
            service.run_external_root()
            assert len(manager._root_tasks) == 2
            with anyio.fail_after(1):
                await ready.wait()

            for _ in range(50):
                await checkpoint()

            assert manager.stats.tasks.total_count == 10
            assert manager.stats.tasks.finished_count == 4
            assert manager.stats.tasks.pending_count == 6
            assert len(manager._root_tasks) >= 1
        finally:
            await manager.stop()

    assert manager.stats.tasks.total_count == 10
    assert manager.stats.tasks.finished_count == 10
    assert manager.stats.tasks.pending_count == 0


async def _run_test_anyio_manager_stats_does_not_count_main_run_method() -> None:
    ready = anyio.Event()

    class StatsTest(Service):
        async def run(self) -> None:
            self.manager.run_task(anyio.sleep_forever)
            ready.set()

    service = StatsTest()
    async with anyio.create_task_group() as tg:
        manager = AnyIOManager(service)
        tg.start_soon(manager.run)  # type: ignore[arg-type]
        await manager.wait_started()

        try:
            with anyio.fail_after(1):  # type: ignore[misc]
                await ready.wait()

            for _ in range(10):
                await checkpoint()

            assert manager.stats.tasks.total_count == 1
            assert manager.stats.tasks.finished_count == 0
            assert manager.stats.tasks.pending_count == 1
        finally:
            await manager.stop()

    assert manager.stats.tasks.total_count == 1
    assert manager.stats.tasks.finished_count == 1
    assert manager.stats.tasks.pending_count == 0


_ENTRYPOINTS = {
    "test_anyio_manager_stats": _run_test_anyio_manager_stats,
    "test_anyio_manager_stats_does_not_count_main_run_method": (
        _run_test_anyio_manager_stats_does_not_count_main_run_method
    ),
}


def _main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in _ENTRYPOINTS:
        print(
            f"Usage: {sys.argv[0]} {{{','.join(_ENTRYPOINTS)}}}",
            file=sys.stderr,
        )
        return 2

    name = sys.argv[1]
    try:
        anyio.run(_ENTRYPOINTS[name], backend="trio")  # type: ignore[arg-type]
        return 0
    except Exception:  # noqa: BLE001
        import traceback

        traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(_main())
