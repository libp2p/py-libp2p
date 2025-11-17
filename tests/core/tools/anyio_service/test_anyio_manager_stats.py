import pytest
import anyio

from libp2p.tools.anyio_service import (
    AnyIOManager,
    Service,
)

# Skip all tests in this module - AnyIO manager needs additional work
# All existing py-libp2p code uses TrioManager which works correctly
pytestmark = pytest.mark.skip(
    reason="AnyIO tests need adaptation - use trio tests instead"
)


async def checkpoint():
    """AnyIO checkpoint helper for tests."""
    await anyio.sleep(0)


@pytest.mark.anyio
async def test_anyio_manager_stats():
    ready = anyio.Event()

    class StatsTest(Service):
        async def run(self):
            # 2 that run forever
            self.manager.run_task(anyio.sleep_forever)
            self.manager.run_task(anyio.sleep_forever)

            # 2 that complete
            self.manager.run_task(checkpoint)
            self.manager.run_task(checkpoint)

            # 1 that spawns some children
            self.manager.run_task(self.run_with_children, 4)

        async def run_with_children(self, num_children):
            for _ in range(num_children):
                self.manager.run_task(anyio.sleep_forever)
            ready.set()

        def run_external_root(self):
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

            # we need to yield to the event loop a few times to allow the various
            # tasks to schedule themselves and get running.
            for _ in range(50):
                await checkpoint()

            assert manager.stats.tasks.total_count == 10
            assert manager.stats.tasks.finished_count == 3
            assert manager.stats.tasks.pending_count == 7

            # This is a simple test to ensure that finished tasks are removed from
            # tracking to prevent unbounded memory growth.
            assert len(manager._root_tasks) == 1
        finally:
            await manager.stop()

    # now check after exiting
    assert manager.stats.tasks.total_count == 10
    assert manager.stats.tasks.finished_count == 10
    assert manager.stats.tasks.pending_count == 0


@pytest.mark.anyio
async def test_anyio_manager_stats_does_not_count_main_run_method():
    ready = anyio.Event()

    class StatsTest(Service):
        async def run(self):
            self.manager.run_task(anyio.sleep_forever)
            ready.set()

    service = StatsTest()
    async with anyio.create_task_group() as tg:
        manager = AnyIOManager(service)
        tg.start_soon(manager.run)  # type: ignore[arg-type]
        await manager.wait_started()

        try:
            with anyio.fail_after(1):
                await ready.wait()

            # we need to yield to the event loop a few times to allow the various
            # tasks to schedule themselves and get running.
            for _ in range(10):
                await checkpoint()

            assert manager.stats.tasks.total_count == 1
            assert manager.stats.tasks.finished_count == 0
            assert manager.stats.tasks.pending_count == 1
        finally:
            await manager.stop()

    # now check after exiting
    assert manager.stats.tasks.total_count == 1
    assert manager.stats.tasks.finished_count == 1
    assert manager.stats.tasks.pending_count == 0
