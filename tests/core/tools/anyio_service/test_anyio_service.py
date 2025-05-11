import pytest
import anyio
import sys

if sys.version_info >= (3, 11):
    from builtins import ExceptionGroup
else:
    from exceptiongroup import ExceptionGroup

from libp2p.tools.anyio_service import (
    Service,
    AnyioManager,
    as_service,
    background_anyio_service,
    DaemonTaskExit,
    LifecycleError,
)

@pytest.mark.anyio
async def test_service_lifecycle():
    class SimpleService(Service):
        async def run(self):
            await anyio.sleep(0.1)

    service = SimpleService()
    async with background_anyio_service(service) as manager:
        assert manager.is_started
        assert manager.is_running
    assert manager.is_finished

@pytest.mark.anyio
async def test_exception_handling():
    class ErrorService(Service):
        async def run(self):
            raise RuntimeError("Service error")

    service = ErrorService()
    manager = AnyioManager(service)

    with pytest.raises(ExceptionGroup) as exc_info:
        await manager.run()
    assert any(isinstance(e, RuntimeError) and str(e) == "Service error" for e in exc_info.value.exceptions)

@pytest.mark.anyio
async def test_task_management():
    task_event = anyio.Event()

    @as_service
    async def TaskService(manager):
        async def task_fn():
            task_event.set()
            manager.cancel() 

        manager.run_task(task_fn)
        await manager.wait_finished()

    async with background_anyio_service(TaskService()):
        with anyio.fail_after(0.1):
            await task_event.wait()


@pytest.mark.anyio
async def test_cancellation_and_cleanup():
    class CancellableService(Service):
        async def run(self):
            await anyio.sleep_forever()

    service = CancellableService()
    async with background_anyio_service(service) as manager:
        assert manager.is_running
        manager.cancel()
    assert manager.is_cancelled
    assert manager.is_finished 