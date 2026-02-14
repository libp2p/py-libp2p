"""Minimal working tests for AnyIOManager service."""

import sys

if sys.version_info >= (3, 11):
    from builtins import ExceptionGroup
else:
    from exceptiongroup import ExceptionGroup

import pytest
import anyio

from libp2p.tools.anyio_service import (
    AnyIOManager,
    LifecycleError,
    Service,
    as_service,
    background_anyio_service,
)


def test_manager_initial_state():
    """Test manager has correct initial state."""
    
    class TestService(Service):
        async def run(self):
            pass
    
    manager = AnyIOManager(TestService())
    
    assert manager.is_started is False
    assert manager.is_running is False
    assert manager.is_cancelled is False
    assert manager.is_finished is False
    assert manager.did_error is False


@pytest.mark.anyio
async def test_service_starts_and_completes():
    """Test service can start and complete."""
    
    @as_service
    async def TestService(manager):
        pass  # Completes immediately
    
    manager = AnyIOManager(TestService())
    await manager.run()
    
    assert manager.is_finished is True
    assert manager.did_error is False


@pytest.mark.anyio
async def test_service_with_background_context():
    """Test service using background context manager."""
    
    class TestService(Service):
        async def run(self):
            # Just wait to be cancelled
            await self.manager.wait_finished()
    
    async with background_anyio_service(TestService()) as manager:
        # Service is running
        assert manager.is_running is True
    
    # After context exit, service should be stopped
    assert manager.is_finished is True
    assert manager.is_cancelled is True


@pytest.mark.anyio
async def test_cannot_cancel_before_start():
    """Test that cancelling before start raises error."""
    
    class TestService(Service):
        async def run(self):
            pass
    
    manager = AnyIOManager(TestService())
    
    with pytest.raises(LifecycleError):
        manager.cancel()


@pytest.mark.anyio
async def test_as_service_decorator():
    """Test @as_service decorator works."""
    
    @as_service
    async def DecoratedService(manager):
        pass
    
    service = DecoratedService()
    assert isinstance(service, Service)
    
    await AnyIOManager.run_service(service)


@pytest.mark.anyio
async def test_service_stats():
    """Test basic stats are available."""
    
    @as_service
    async def TestService(manager):
        pass
    
    manager = AnyIOManager(TestService())
    await manager.run()
    
    stats = manager.stats
    assert stats is not None
    assert hasattr(stats, 'tasks')


@pytest.mark.anyio
async def test_service_get_manager():
    """Test service can access manager."""
    
    class TestService(Service):
        async def run(self):
            mgr = self.get_manager()
            assert mgr is not None
            assert mgr.is_running is True
    
    await AnyIOManager.run_service(TestService())


@pytest.mark.anyio
async def test_service_can_wait_started():
    """Test wait_started works correctly."""
    
    class TestService(Service):
        async def run(self):
            await anyio.sleep(0.01)
    
    manager = AnyIOManager(TestService())
    
    async with anyio.create_task_group() as tg:
        tg.start_soon(manager.run)
        
        # Should complete quickly
        with anyio.fail_after(1.0):
            await manager.wait_started()
        
        assert manager.is_started is True


@pytest.mark.anyio
async def test_service_cancellation():
    """Test that service can be cancelled."""
    
    class TestService(Service):
        async def run(self):
            await self.manager.wait_finished()
    
    manager = AnyIOManager(TestService())
    
    async with anyio.create_task_group() as tg:
        tg.start_soon(manager.run)
        await manager.wait_started()
        
        # Cancel the service
        manager.cancel()
        
        with anyio.fail_after(1.0):
            await manager.wait_finished()
        
        assert manager.is_cancelled is True
        assert manager.is_finished is True
