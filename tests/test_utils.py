import trio
import pytest
from libp2p.utils import TrioQueue


@pytest.mark.trio
async def test_trio_queue():
    queue = TrioQueue()

    async def queue_get(task_status=None):
        result = await queue.get()
        task_status.started(result)

    async with trio.open_nursery() as nursery:
        nursery.start_soon(queue.put, 123)
        result = await nursery.start(queue_get)

    assert result == 123

