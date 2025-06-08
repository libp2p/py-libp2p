import sys

if sys.version_info >= (3, 11):
    from builtins import (
        ExceptionGroup,
    )
else:
    from exceptiongroup import (
        ExceptionGroup,
    )

import pytest
import trio

from libp2p.tools.async_service import (
    LifecycleError,
    Service,
    TrioManager,
    as_service,
    background_trio_service,
)


class WaitCancelledService(Service):
    async def run(self) -> None:
        await self.manager.wait_finished()


async def do_service_lifecycle_check(
    manager, manager_run_fn, trigger_exit_condition_fn, should_be_cancelled
):
    async with trio.open_nursery() as nursery:
        assert manager.is_started is False
        assert manager.is_running is False
        assert manager.is_cancelled is False
        assert manager.is_finished is False

        nursery.start_soon(manager_run_fn)

        with trio.fail_after(0.1):
            await manager.wait_started()

        assert manager.is_started is True
        assert manager.is_running is True
        assert manager.is_cancelled is False
        assert manager.is_finished is False

        # trigger the service to exit
        trigger_exit_condition_fn()

        with trio.fail_after(0.1):
            await manager.wait_finished()

        if should_be_cancelled:
            assert manager.is_started is True
            # We cannot determine whether the service should be running at this
            # stage because a service is considered running until it is
            # finished.  Since it may be cancelled but still not finished we
            # can't know.
            assert manager.is_cancelled is True
            # We also cannot determine whether a service should be finished at this
            # stage as it could have exited cleanly and is now finished or it
            # might be doing some cleanup after which it will register as being
            # finished.
            assert manager.is_running is True or manager.is_finished is True

        assert manager.is_started is True
        assert manager.is_running is False
        assert manager.is_cancelled is should_be_cancelled
        assert manager.is_finished is True


def test_service_manager_initial_state():
    service = WaitCancelledService()
    manager = TrioManager(service)

    assert manager.is_started is False
    assert manager.is_running is False
    assert manager.is_cancelled is False
    assert manager.is_finished is False


@pytest.mark.trio
async def test_trio_service_lifecycle_run_and_clean_exit():
    trigger_exit = trio.Event()

    @as_service
    async def ServiceTest(manager):
        await trigger_exit.wait()

    service = ServiceTest()
    manager = TrioManager(service)

    await do_service_lifecycle_check(
        manager=manager,
        manager_run_fn=manager.run,
        trigger_exit_condition_fn=trigger_exit.set,
        should_be_cancelled=False,
    )


@pytest.mark.trio
async def test_trio_service_lifecycle_run_and_external_cancellation():
    @as_service
    async def ServiceTest(manager):
        await trio.sleep_forever()

    service = ServiceTest()
    manager = TrioManager(service)

    await do_service_lifecycle_check(
        manager=manager,
        manager_run_fn=manager.run,
        trigger_exit_condition_fn=manager.cancel,
        should_be_cancelled=True,
    )


@pytest.mark.trio
async def test_trio_service_lifecycle_run_and_exception():
    trigger_error = trio.Event()

    @as_service
    async def ServiceTest(manager):
        await trigger_error.wait()
        raise RuntimeError("Service throwing error")

    service = ServiceTest()
    manager = TrioManager(service)

    async def do_service_run():
        with pytest.raises(ExceptionGroup):
            await manager.run()

    await do_service_lifecycle_check(
        manager=manager,
        manager_run_fn=do_service_run,
        trigger_exit_condition_fn=trigger_error.set,
        should_be_cancelled=True,
    )


@pytest.mark.trio
async def test_trio_service_lifecycle_run_and_task_exception():
    trigger_error = trio.Event()

    @as_service
    async def ServiceTest(manager):
        async def task_fn():
            await trigger_error.wait()
            raise RuntimeError("Service throwing error")

        manager.run_task(task_fn)

    service = ServiceTest()
    manager = TrioManager(service)

    async def do_service_run():
        with pytest.raises(ExceptionGroup):
            await manager.run()

    await do_service_lifecycle_check(
        manager=manager,
        manager_run_fn=do_service_run,
        trigger_exit_condition_fn=trigger_error.set,
        should_be_cancelled=True,
    )


@pytest.mark.trio
async def test_sub_service_cancelled_when_parent_stops():
    ready_cancel = trio.Event()

    # This test runs a service that runs a sub-service that sleeps forever. When the
    # parent exits, the sub-service should be cancelled as well.
    @as_service
    async def WaitForeverService(manager):
        ready_cancel.set()
        await manager.wait_finished()

    sub_manager = TrioManager(WaitForeverService())

    @as_service
    async def ServiceTest(manager):
        async def run_sub():
            await sub_manager.run()

        manager.run_task(run_sub)
        await manager.wait_finished()

    s = ServiceTest()
    async with background_trio_service(s) as manager:
        await ready_cancel.wait()

    assert not manager.is_running
    assert manager.is_cancelled
    assert manager.is_finished

    assert not sub_manager.is_running
    assert not sub_manager.is_cancelled
    assert sub_manager.is_finished


@pytest.mark.trio
async def test_trio_service_lifecycle_run_and_daemon_task_exit():
    trigger_error = trio.Event()

    @as_service
    async def ServiceTest(manager):
        async def daemon_task_fn():
            await trigger_error.wait()

        manager.run_daemon_task(daemon_task_fn)
        await manager.wait_finished()

    service = ServiceTest()
    manager = TrioManager(service)

    async def do_service_run():
        with pytest.raises(ExceptionGroup):
            await manager.run()

    await do_service_lifecycle_check(
        manager=manager,
        manager_run_fn=do_service_run,
        trigger_exit_condition_fn=trigger_error.set,
        should_be_cancelled=True,
    )


@pytest.mark.trio
async def test_exceptiongroup_in_run():
    # This test should cause TrioManager.run() to explicitly raise an ExceptionGroup
    # containing two exceptions -- one raised inside its run() method and another
    # raised by the daemon task exiting early.
    trigger_error = trio.Event()

    class ServiceTest(Service):
        async def run(self):
            ready = trio.Event()
            self.manager.run_task(self.error_fn, ready)
            await ready.wait()
            trigger_error.set()
            raise RuntimeError("Exception inside Service.run()")

        async def error_fn(self, ready):
            ready.set()
            await trigger_error.wait()
            raise ValueError("Exception inside error_fn")

    with pytest.raises(ExceptionGroup) as exc_info:
        await TrioManager.run_service(ServiceTest())

    exc = exc_info.value
    assert len(exc.exceptions) == 2
    assert any(isinstance(err, RuntimeError) for err in exc.exceptions)
    assert any(isinstance(err, ValueError) for err in exc.exceptions)


@pytest.mark.trio
async def test_trio_service_background_service_context_manager():
    service = WaitCancelledService()

    async with background_trio_service(service) as manager:
        # ensure the manager property is set.
        assert hasattr(service, "manager")
        assert service.get_manager() is manager

        assert manager.is_started is True
        assert manager.is_running is True
        assert manager.is_cancelled is False
        assert manager.is_finished is False

    assert manager.is_started is True
    assert manager.is_running is False
    assert manager.is_cancelled is True
    assert manager.is_finished is True


@pytest.mark.trio
async def test_trio_service_manager_stop():
    service = WaitCancelledService()

    async with background_trio_service(service) as manager:
        assert manager.is_started is True
        assert manager.is_running is True
        assert manager.is_cancelled is False
        assert manager.is_finished is False

        await manager.stop()

        assert manager.is_started is True
        assert manager.is_running is False
        assert manager.is_cancelled is True
        assert manager.is_finished is True


@pytest.mark.trio
async def test_trio_service_manager_run_task():
    task_event = trio.Event()

    @as_service
    async def RunTaskService(manager):
        async def task_fn():
            task_event.set()

        manager.run_task(task_fn)
        await manager.wait_finished()

    async with background_trio_service(RunTaskService()):
        with trio.fail_after(0.1):
            await task_event.wait()


@pytest.mark.trio
async def test_trio_service_manager_run_task_waits_for_task_completion():
    task_event = trio.Event()

    @as_service
    async def RunTaskService(manager):
        async def task_fn():
            await trio.sleep(0.01)
            task_event.set()

        manager.run_task(task_fn)
        # the task is set to run in the background but then  the service exits.
        # We want to be sure that the task is allowed to continue till
        # completion unless explicitely cancelled.

    async with background_trio_service(RunTaskService()):
        with trio.fail_after(0.1):
            await task_event.wait()


@pytest.mark.trio
async def test_trio_service_manager_run_task_can_still_cancel_after_run_finishes():
    task_event = trio.Event()
    service_finished = trio.Event()

    @as_service
    async def RunTaskService(manager):
        async def task_fn():
            # this will never complete
            await task_event.wait()

        manager.run_task(task_fn)
        # the task is set to run in the background but then  the service exits.
        # We want to be sure that the task is allowed to continue till
        # completion unless explicitely cancelled.
        service_finished.set()

    async with background_trio_service(RunTaskService()) as manager:
        with trio.fail_after(0.01):
            await service_finished.wait()

        # show that the service hangs waiting for the task to complete.
        with trio.move_on_after(0.01) as cancel_scope:
            await manager.wait_finished()
        assert cancel_scope.cancelled_caught is True

        # trigger cancellation and see that the service actually stops
        manager.cancel()
        with trio.fail_after(0.01):
            await manager.wait_finished()


@pytest.mark.trio
async def test_trio_service_manager_run_task_reraises_exceptions():
    task_event = trio.Event()

    @as_service
    async def RunTaskService(manager):
        async def task_fn():
            await task_event.wait()
            raise Exception("task exception in run_task")

        manager.run_task(task_fn)
        with trio.fail_after(1):
            await trio.sleep_forever()

    with pytest.raises(ExceptionGroup):
        async with background_trio_service(RunTaskService()):
            task_event.set()
            with trio.fail_after(1):
                await trio.sleep_forever()


@pytest.mark.trio
async def test_trio_service_manager_run_daemon_task_cancels_if_exits():
    task_event = trio.Event()

    @as_service
    async def RunTaskService(manager):
        async def daemon_task_fn():
            await task_event.wait()

        manager.run_daemon_task(daemon_task_fn, name="daemon_task_fn")
        with trio.fail_after(1):
            await trio.sleep_forever()

    with pytest.raises(ExceptionGroup):
        async with background_trio_service(RunTaskService()):
            task_event.set()
            with trio.fail_after(1):
                await trio.sleep_forever()


@pytest.mark.trio
async def test_trio_service_manager_propogates_and_records_exceptions():
    @as_service
    async def ThrowErrorService(manager):
        raise RuntimeError("this is the error")

    service = ThrowErrorService()
    manager = TrioManager(service)

    assert manager.did_error is False

    with pytest.raises(ExceptionGroup):
        await manager.run()

    assert manager.did_error is True


@pytest.mark.trio
async def test_trio_service_lifecycle_run_and_clean_exit_with_child_service():
    trigger_exit = trio.Event()

    @as_service
    async def ChildServiceTest(manager):
        await trigger_exit.wait()

    @as_service
    async def ServiceTest(manager):
        child_manager = manager.run_child_service(ChildServiceTest())
        await child_manager.wait_started()

    service = ServiceTest()
    manager = TrioManager(service)

    await do_service_lifecycle_check(
        manager=manager,
        manager_run_fn=manager.run,
        trigger_exit_condition_fn=trigger_exit.set,
        should_be_cancelled=False,
    )


@pytest.mark.trio
async def test_trio_service_with_daemon_child_service():
    ready = trio.Event()

    @as_service
    async def ChildServiceTest(manager):
        await manager.wait_finished()

    @as_service
    async def ServiceTest(manager):
        child_manager = manager.run_daemon_child_service(ChildServiceTest())
        await child_manager.wait_started()
        ready.set()
        await manager.wait_finished()

    service = ServiceTest()
    async with background_trio_service(service):
        await ready.wait()


@pytest.mark.trio
async def test_trio_service_with_daemon_child_task():
    ready = trio.Event()
    started = trio.Event()

    async def _task():
        started.set()
        await trio.sleep(100)

    @as_service
    async def ServiceTest(manager):
        manager.run_daemon_task(_task)
        await started.wait()
        ready.set()
        await manager.wait_finished()

    service = ServiceTest()
    async with background_trio_service(service):
        await ready.wait()


@pytest.mark.trio
async def test_trio_service_with_async_generator():
    is_within_agen = trio.Event()

    async def do_agen():
        while True:
            yield

    @as_service
    async def ServiceTest(manager):
        async for _ in do_agen():  # noqa: F841
            await trio.lowlevel.checkpoint()
            is_within_agen.set()

    async with background_trio_service(ServiceTest()) as manager:
        await is_within_agen.wait()
        manager.cancel()


@pytest.mark.trio
async def test_trio_service_disallows_task_scheduling_when_not_running():
    class ServiceTest(Service):
        async def run(self):
            await self.manager.wait_finished()

        def do_schedule(self):
            self.manager.run_task(trio.sleep, 1)

    service = ServiceTest()

    async with background_trio_service(service):
        service.do_schedule()

    with pytest.raises(LifecycleError):
        service.do_schedule()


@pytest.mark.trio
async def test_trio_service_disallows_task_scheduling_after_cancel():
    @as_service
    async def ServiceTest(manager):
        manager.cancel()
        manager.run_task(trio.sleep, 1)

    await TrioManager.run_service(ServiceTest())


@pytest.mark.trio
async def test_trio_service_cancellation_with_running_daemon_task():
    in_daemon = trio.Event()

    class ServiceTest(Service):
        async def run(self):
            self.manager.run_daemon_task(self._do_daemon)
            await self.manager.wait_finished()

        async def _do_daemon(self):
            in_daemon.set()
            while self.manager.is_running:
                await trio.lowlevel.checkpoint()

    async with background_trio_service(ServiceTest()) as manager:
        await in_daemon.wait()
        manager.cancel()


@pytest.mark.trio
async def test_trio_service_with_try_finally_cleanup():
    ready_cancel = trio.Event()

    class TryFinallyService(Service):
        cleanup_up = False

        async def run(self) -> None:
            try:
                ready_cancel.set()
                await self.manager.wait_finished()
            finally:
                self.cleanup_up = True

    service = TryFinallyService()
    async with background_trio_service(service) as manager:
        await ready_cancel.wait()
        assert not service.cleanup_up
        manager.cancel()
    assert service.cleanup_up


@pytest.mark.trio
async def test_trio_service_with_try_finally_cleanup_with_unshielded_await():
    ready_cancel = trio.Event()

    class TryFinallyService(Service):
        cleanup_up = False

        async def run(self) -> None:
            try:
                ready_cancel.set()
                await self.manager.wait_finished()
            finally:
                await trio.lowlevel.checkpoint()
                self.cleanup_up = True

    service = TryFinallyService()
    async with background_trio_service(service) as manager:
        await ready_cancel.wait()
        assert not service.cleanup_up
        manager.cancel()
    assert not service.cleanup_up


@pytest.mark.trio
async def test_trio_service_with_try_finally_cleanup_with_shielded_await():
    ready_cancel = trio.Event()

    class TryFinallyService(Service):
        cleanup_up = False

        async def run(self) -> None:
            try:
                ready_cancel.set()
                await self.manager.wait_finished()
            finally:
                with trio.CancelScope(shield=True):  # type: ignore[call-arg]
                    await trio.lowlevel.checkpoint()
                self.cleanup_up = True

    service = TryFinallyService()
    async with background_trio_service(service) as manager:
        await ready_cancel.wait()
        assert not service.cleanup_up
        manager.cancel()
    assert service.cleanup_up


@pytest.mark.trio
async def test_error_in_service_run():
    class ServiceTest(Service):
        async def run(self):
            self.manager.run_daemon_task(self.manager.wait_finished)
            raise ValueError("Exception inside run()")

    with pytest.raises(ExceptionGroup):
        await TrioManager.run_service(ServiceTest())


@pytest.mark.trio
async def test_daemon_task_finishes_leaving_children():
    class ServiceTest(Service):
        async def sleep_and_fail(self):
            await trio.sleep(1)
            raise AssertionError(
                "This should not happen as the task should be cancelled"
            )

        async def buggy_daemon(self):
            self.manager.run_task(self.sleep_and_fail)

        async def run(self):
            self.manager.run_daemon_task(self.buggy_daemon)

    with pytest.raises(ExceptionGroup):
        await TrioManager.run_service(ServiceTest())
