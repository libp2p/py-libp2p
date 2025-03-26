"""
Test suite for validating the anyio-based service implementation.
Focuses on lifecycle management, error handling, and concurrency control.
"""
import asyncio
import random

import pytest
import anyio

from libp2p.tools.anyio_service import (
    LifecycleError,
    Service,
)
from libp2p.tools.anyio_service.manager import (
    AnyIOManager,
    background_anyio_service,
)


class CountingService(Service):
    """A simple service that counts up on a timer."""

    def __init__(self, count_interval: float = 0.01):
        super().__init__()
        self.count_interval = count_interval
        self.count = 0
        self.paused = False
        self.error_at = None
        self.exit_at = None

    async def run(self) -> None:
        while self.manager.is_running:
            if not self.paused:
                self.count += 1
                if self.error_at is not None and self.count >= self.error_at:
                    raise ValueError(f"Simulated error at count {self.count}")
                if self.exit_at is not None and self.count >= self.exit_at:
                    break
            await anyio.sleep(self.count_interval)


# Lifecycle and Cancellation Tests


@pytest.mark.asyncio
async def test_service_cancellation():
    """Test service cancellation functionality."""
    service = CountingService()

    async with background_anyio_service(service) as manager:
        await asyncio.sleep(0.1)
        initial_count = service.count
        assert initial_count > 0

        manager.cancel()
        await manager.wait_finished()
        assert not manager.is_running
        assert manager.is_cancelled
        assert manager.is_finished

        await asyncio.sleep(0.1)  # Ensure count stops
        assert service.count == initial_count


@pytest.mark.asyncio
async def test_service_double_start():
    """Test that a service cannot be started twice."""
    service = CountingService()

    async with background_anyio_service(service):
        with pytest.raises(LifecycleError):
            async with background_anyio_service(service):
                pass  # Attempting to start again should fail


# Error Handling Tests


@pytest.mark.asyncio
async def test_service_error_propagation():
    service = CountingService()
    service.error_at = 5
    with pytest.raises(ExceptionGroup) as exc_info:
        async with background_anyio_service(service):
            await anyio.sleep(1)
    # Check the nested exceptions
    assert len(exc_info.value.exceptions) == 1
    inner_group = exc_info.value.exceptions[0]
    assert isinstance(inner_group, ExceptionGroup)
    assert any(
        isinstance(e, ValueError) and str(e) == "Simulated error at count 5"
        for e in inner_group.exceptions
    )


@pytest.mark.asyncio
async def test_nested_service_error_propagation():
    class ParentService(Service):
        def __init__(self):
            super().__init__()
            self.child = CountingService()
            self.child.error_at = 5

        async def run(self):
            self.manager.run_daemon_task(self.run_child)
            while self.manager.is_running:
                await anyio.sleep(0.1)

        async def run_child(self):
            async with background_anyio_service(self.child):
                while self.manager.is_running:  # Keep child alive
                    await anyio.sleep(0.1)

    parent = ParentService()
    with pytest.raises(ExceptionGroup):
        async with background_anyio_service(parent):
            await anyio.sleep(1)


# Daemon Task Tests


@pytest.mark.asyncio
async def test_daemon_task_lifecycle():
    with anyio.fail_after(5):
        task_started = False
        task_cleaned_up = False

        class DaemonTaskService(Service):
            async def run(self):
                self.manager.run_daemon_task(self.daemon_task)
                while self.manager.is_running:
                    await anyio.sleep(0.05)

            async def daemon_task(self):
                nonlocal task_started, task_cleaned_up
                task_started = True
                try:
                    while self.manager.is_running:  # Respect manager's lifecycle
                        await anyio.sleep(0.05)
                finally:
                    task_cleaned_up = True

        service = DaemonTaskService()
        async with background_anyio_service(service) as manager:
            await anyio.sleep(0.1)
            assert task_started  # Verify task starts before stopping
        await manager.stop()  # Ensure all tasks are cancelled
        await manager.wait_finished()  # Wait for full cleanup

        assert task_started
        assert task_cleaned_up


@pytest.mark.asyncio
async def test_daemon_task_error_propagation():
    class ErrorDaemonService(Service):
        async def run(self):
            self.manager.run_daemon_task(self.error_task)
            while self.manager.is_running:
                await anyio.sleep(0.1)

        async def error_task(self):
            await anyio.sleep(0.1)
            raise ValueError("Daemon task error")

    service = ErrorDaemonService()
    with pytest.raises(ExceptionGroup) as exc_info:
        async with background_anyio_service(service):
            await anyio.sleep(1)
    # Check nested exceptions
    assert len(exc_info.value.exceptions) == 1
    inner_group = exc_info.value.exceptions[0]
    assert isinstance(inner_group, ExceptionGroup)
    assert any(
        isinstance(e, ValueError) and str(e) == "Daemon task error"
        for e in inner_group.exceptions
    )


@pytest.mark.asyncio
async def test_daemon_task_normal_exit():
    task_exited = False
    service_continued = False

    class ExitingDaemonService(Service):
        async def run(self):
            self.manager.run_daemon_task(self.exiting_task)
            await anyio.sleep(0.3)
            nonlocal service_continued
            service_continued = True

        async def exiting_task(self):
            await anyio.sleep(0.1)
            nonlocal task_exited
            task_exited = True

    service = ExitingDaemonService()
    async with background_anyio_service(service):
        await anyio.sleep(0.5)
    assert task_exited
    assert service_continued


# Concurrency Tests


@pytest.mark.asyncio
async def test_multiple_services_concurrency():
    services = [CountingService() for _ in range(3)]
    managers = []

    # Run services concurrently with a timeout
    async with anyio.create_task_group() as tg:
        for s in services:
            manager = AnyIOManager(s)
            managers.append(manager)
            tg.start_soon(manager.run)  # Start the service

        # Allow services to run briefly, then cancel
        await anyio.sleep(0.2)  # Let them count for 0.2 seconds
        for m in managers:
            m.cancel()  # Cancel all managers within the task group

    # Wait for all managers to finish
    for m in managers:
        await m.wait_finished()

    # Verify results
    assert all(not m.is_running for m in managers)
    assert all(s.count > 0 for s in services)


@pytest.mark.asyncio
async def test_resource_cleanup_under_load():
    """Test resource cleanup under high concurrency load."""

    class ResourceService(Service):
        def __init__(self):
            super().__init__()
            self.resources: set[int] = set()
            self.max_resources = 0
            self.all_allocated: set[int] = set()

        async def run(self):
            for i in range(50):
                self.manager.run_daemon_task(self.allocate_resources, i)
            await asyncio.sleep(0.3)  # Run for a while

        async def allocate_resources(self, task_id: int):
            local_resources: set[int] = set()
            resource_id = 1000 * task_id
            try:
                while self.manager.is_running:
                    resource_id += 1
                    self.resources.add(resource_id)
                    self.all_allocated.add(resource_id)
                    local_resources.add(resource_id)
                    self.max_resources = max(self.max_resources, len(self.resources))
                    if random.random() < 0.7 and local_resources:
                        to_free = random.choice(list(local_resources))
                        local_resources.remove(to_free)
                        self.resources.remove(to_free)
                    await asyncio.sleep(0.001)
            finally:
                for r in local_resources:
                    self.resources.remove(r)

    service = ResourceService()

    async with background_anyio_service(service):
        pass

    assert len(service.resources) == 0  # All resources cleaned up
    assert service.max_resources > 0  # Resources were allocated


# Stress Tests


@pytest.mark.asyncio
async def test_rapid_start_stop():
    """Test rapidly starting and stopping services."""
    for _ in range(50):
        service = CountingService(count_interval=0.001)
        async with background_anyio_service(service):
            await asyncio.sleep(0.01)
        assert not service.manager.is_running
        assert service.manager.is_finished


@pytest.mark.asyncio
async def test_stress_nested_services():
    class NestedService(Service):
        def __init__(self, depth: int, max_depth: int):
            super().__init__()
            self.depth = depth
            self.max_depth = max_depth
            self.child = None
            if depth < max_depth:
                self.child = NestedService(depth + 1, max_depth)
            self.count = 0

        async def run(self):
            if self.child:
                async with background_anyio_service(self.child):
                    while self.manager.is_running:
                        self.count += 1
                        await anyio.sleep(0.001)
            else:
                while self.manager.is_running:
                    self.count += 1
                    await anyio.sleep(0.001)

    root_service = NestedService(0, 20)
    async with background_anyio_service(root_service):
        await anyio.sleep(0.1)
    current = root_service
    while current:
        assert not current.manager.is_running
        assert current.manager.is_finished
        assert current.count > 0
        current = current.child


@pytest.mark.asyncio
async def test_concurrent_task_cancellation():
    class ManyTasksService(Service):
        def __init__(self):
            super().__init__()
            self.tasks_started = 0
            self.tasks_cleaned = 0

        async def run(self):
            for i in range(500):
                self.manager.run_task(self.long_task, i)

        async def long_task(self, task_id: int):
            self.tasks_started += 1
            try:
                while self.manager.is_running:  # Check manager state
                    await anyio.sleep(0.01)
            finally:
                self.tasks_cleaned += 1

    service = ManyTasksService()
    async with background_anyio_service(service) as manager:
        await anyio.sleep(0.1)  # Let tasks start
        manager.cancel()  # Cancel all tasks
        await manager.wait_finished()  # Wait for cleanup
    assert service.tasks_started == 500
    assert service.tasks_cleaned == 500


# Integration Tests


@pytest.mark.asyncio
async def test_service_manager_as_context_manager():
    """Test using ServiceManager as a context manager."""
    service = CountingService()

    async with background_anyio_service(service) as manager:
        await asyncio.sleep(0.1)
        assert manager.is_running
        assert service.count > 0

    assert not manager.is_running
    assert manager.is_finished

    with pytest.raises(LifecycleError):  # Cannot restart
        async with background_anyio_service(service):
            pass


@pytest.mark.asyncio
async def test_graceful_shutdown_with_pending_tasks():
    shutdown_order = []

    class ShutdownTestService(Service):
        def __init__(self, name):
            super().__init__()
            self.name = name

        async def run(self):
            try:
                while self.manager.is_running:
                    await anyio.sleep(0.05)
            finally:
                shutdown_order.append(f"service:{self.name}")

    class ParentService(Service):
        async def run(self):
            child1 = ShutdownTestService("child1")
            child2 = ShutdownTestService("child2")
            async with background_anyio_service(child1):
                async with background_anyio_service(child2):
                    try:
                        async with anyio.create_task_group() as tg:
                            tg.start_soon(self.daemon1)
                            tg.start_soon(self.daemon2)
                            while self.manager.is_running:
                                await anyio.sleep(0.05)
                    finally:
                        shutdown_order.append(
                            "service:parent"
                        )  # Append in finally block

        async def daemon1(self):
            try:
                while self.manager.is_running:
                    await anyio.sleep(0.05)
            finally:
                shutdown_order.append("daemon:1")

        async def daemon2(self):
            try:
                while self.manager.is_running:
                    await anyio.sleep(0.05)
            finally:
                shutdown_order.append("daemon:2")

    parent = ParentService()
    async with background_anyio_service(parent) as manager:
        await anyio.sleep(0.2)  # Let everything start
        manager.cancel()  # Explicitly cancel
        await manager.wait_finished()  # Wait for all tasks

    # Verify shutdown order
    assert "daemon:1" in shutdown_order
    assert "daemon:2" in shutdown_order
    assert "service:parent" in shutdown_order
    assert "service:child1" in shutdown_order
    assert "service:child2" in shutdown_order

    daemon1_idx = shutdown_order.index("daemon:1")
    daemon2_idx = shutdown_order.index("daemon:2")
    parent_idx = shutdown_order.index("service:parent")

    assert daemon1_idx < parent_idx
    assert daemon2_idx < parent_idx
