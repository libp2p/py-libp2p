import pytest
import trio
from trio.testing import (
    wait_all_tasks_blocked,
)


@pytest.mark.trio
async def test_swarm_conn_close(swarm_conn_pair):
    conn_0, conn_1 = swarm_conn_pair

    assert not conn_0.is_closed
    assert not conn_1.is_closed

    await conn_0.close()

    await trio.sleep(0.1)
    await wait_all_tasks_blocked()

    assert conn_0.is_closed
    assert conn_1.is_closed
    assert conn_0 not in conn_0.swarm.connections.values()
    assert conn_1 not in conn_1.swarm.connections.values()


@pytest.mark.trio
async def test_swarm_conn_streams(swarm_conn_pair):
    conn_0, conn_1 = swarm_conn_pair

    assert len(conn_0.get_streams()) == 0
    assert len(conn_1.get_streams()) == 0

    stream_0_0 = await conn_0.new_stream()
    await trio.sleep(0.01)
    assert len(conn_0.get_streams()) == 1
    assert len(conn_1.get_streams()) == 1

    stream_0_1 = await conn_0.new_stream()
    await trio.sleep(0.01)
    assert len(conn_0.get_streams()) == 2
    assert len(conn_1.get_streams()) == 2

    conn_0.remove_stream(stream_0_0)
    assert len(conn_0.get_streams()) == 1
    conn_0.remove_stream(stream_0_1)
    assert len(conn_0.get_streams()) == 0
    # Nothing happen if `stream_0_1` is not present or already removed.
    conn_0.remove_stream(stream_0_1)
