# Copied from https://github.com/ethereum/async-service
import sys

import pytest
import trio

if sys.version_info >= (3, 11):
    from builtins import (
        ExceptionGroup,
    )
else:
    from exceptiongroup import ExceptionGroup

from libp2p.tools.async_service import (
    LifecycleError,
    Service,
    background_trio_service,
)
from libp2p.tools.async_service.trio_service import (
    external_api,
)


class ExternalAPIService(Service):
    async def run(self):
        await self.manager.wait_finished()

    @external_api
    async def get_7(self, wait_return=None, signal_event=None):
        if signal_event is not None:
            signal_event.set()
        if wait_return is not None:
            await wait_return.wait()
        return 7


@pytest.mark.trio
async def test_trio_service_external_api_fails_before_start():
    service = ExternalAPIService()

    # should raise if the service has not yet been started.
    with pytest.raises(LifecycleError):
        await service.get_7()


@pytest.mark.trio
async def test_trio_service_external_api_works_while_running():
    service = ExternalAPIService()

    async with background_trio_service(service):
        assert await service.get_7() == 7


@pytest.mark.trio
async def test_trio_service_external_api_raises_when_cancelled():
    service = ExternalAPIService()

    async with background_trio_service(service) as manager:
        with pytest.raises(ExceptionGroup):
            async with trio.open_nursery() as nursery:
                # an event to ensure that we are indeed within the body of the
                is_within_fn = trio.Event()
                trigger_return = trio.Event()

                nursery.start_soon(service.get_7, trigger_return, is_within_fn)

                # ensure we're within the body of the task.
                await is_within_fn.wait()

                # now cancel the service and trigger the return of the function.
                manager.cancel()

                # exiting the context block here will cause the background task
                # to complete and shold raise the exception

        # A direct call should also fail.  This *should* be hitting the early
        # return mechanism.
        with pytest.raises(LifecycleError):
            assert await service.get_7()


@pytest.mark.trio
async def test_trio_service_external_api_raises_when_finished():
    service = ExternalAPIService()

    async with background_trio_service(service) as manager:
        pass

    assert manager.is_finished
    # A direct call should also fail.  This *should* be hitting the early
    # return mechanism.
    with pytest.raises(LifecycleError):
        assert await service.get_7()


@pytest.mark.trio
async def test_trio_external_api_call_that_schedules_task():
    done = trio.Event()

    class MyService(Service):
        async def run(self):
            await self.manager.wait_finished()

        @external_api
        async def do_scheduling(self):
            self.manager.run_task(self.set_done)

        async def set_done(self):
            done.set()

    service = MyService()
    async with background_trio_service(service):
        await service.do_scheduling()
        with trio.fail_after(1):
            await done.wait()
