import pytest
import trio

from libp2p.tools.async_service import (
    Service,
)
from libp2p.tools.async_service.trio_service import TrioManager


@pytest.mark.trio
async def test_trio_manager_stats():
    ready = trio.Event()

    class StatsTest(Service):
        async def run(self):
            # 2 that run forever
            self.manager.run_task(trio.sleep_forever)
            self.manager.run_task(trio.sleep_forever)

            # 2 that complete
            self.manager.run_task(trio.lowlevel.checkpoint)
            self.manager.run_task(trio.lowlevel.checkpoint)

            # 1 that spawns some children
            self.manager.run_task(self.run_with_children, 4)

        async def run_with_children(self, num_children):
            for _ in range(num_children):
                self.manager.run_task(trio.sleep_forever)
            ready.set()

        def run_external_root(self):
            self.manager.run_task(trio.lowlevel.checkpoint)

    service = StatsTest()
    async with trio.open_nursery() as nursery:
        manager = TrioManager(service)
        nursery.start_soon(manager.run)
        await manager.wait_started()

        try:
            service.run_external_root()
            assert len(manager._root_tasks) == 2
            with trio.fail_after(1):
                await ready.wait()

            # we need to yield to the event loop a few times to allow the various
            # tasks to schedule themselves and get running.
            for _ in range(50):
                await trio.lowlevel.checkpoint()

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


@pytest.mark.trio
async def test_trio_manager_stats_does_not_count_main_run_method():
    ready = trio.Event()

    class StatsTest(Service):
        async def run(self):
            self.manager.run_task(trio.sleep_forever)
            ready.set()

    service = StatsTest()
    async with trio.open_nursery() as nursery:
        manager = TrioManager(service)
        nursery.start_soon(manager.run)
        await manager.wait_started()

        try:
            with trio.fail_after(1):
                await ready.wait()

            # we need to yield to the event loop a few times to allow the various
            # tasks to schedule themselves and get running.
            for _ in range(10):
                await trio.lowlevel.checkpoint()

            assert manager.stats.tasks.total_count == 1
            assert manager.stats.tasks.finished_count == 0
            assert manager.stats.tasks.pending_count == 1
        finally:
            await manager.stop()

    # now check after exiting
    assert manager.stats.tasks.total_count == 1
    assert manager.stats.tasks.finished_count == 1
    assert manager.stats.tasks.pending_count == 0
