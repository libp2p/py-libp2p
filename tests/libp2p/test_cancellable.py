import asyncio
import gc
from pprint import pprint

import pytest

from libp2p.cancellable import Cancellable


class Example(Cancellable):
    def __init__(self) -> None:
        super().__init__()


class ExampleException(Exception):
    pass


async def i_am_blocked_forever() -> None:
    event = asyncio.Event()
    await event.wait()


async def i_raise_example_exception() -> None:
    raise ExampleException


@pytest.mark.asyncio
async def test_cancellable():
    e = Example()
    assert len(e._tasks) == 0
    e.run_task(i_am_blocked_forever())
    assert len(e._tasks) == 1
    task = tuple(e._tasks)[0]
    await e.cancel()
    assert task.done()


@pytest.mark.asyncio
async def test_cancellable_exception_raised():
    e = Example()
    e.run_task(i_raise_example_exception())
    await asyncio.sleep(0)
    with pytest.raises(ExampleException):
        await e.cancel()
