import pytest
import trio


async def _wait_for_conn_closed(conn, *, timeout: float = 5.0) -> None:
    """Wait for connection to be closed (event-based, no arbitrary sleeps)."""
    with trio.fail_after(timeout):
        await conn.event_closed.wait()


async def _wait_for_stream_count(conn, expected: int, *, timeout: float = 5.0) -> None:
    """Wait until connection has at least `expected` streams (event-based)."""
    with trio.fail_after(timeout):
        while len(conn.get_streams()) < expected:
            await trio.sleep(0)  # Yield to let other tasks run


@pytest.mark.trio
async def test_swarm_conn_close(swarm_conn_pair):
    conn_0, conn_1 = swarm_conn_pair

    assert not conn_0.is_closed
    assert not conn_1.is_closed

    await conn_0.close()

    # Wait for conn_1 to observe the closed connection (event-based, not arbitrary time)
    await _wait_for_conn_closed(conn_1)

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
    await _wait_for_stream_count(conn_1, 1)
    assert len(conn_0.get_streams()) == 1
    assert len(conn_1.get_streams()) == 1

    stream_0_1 = await conn_0.new_stream()
    await _wait_for_stream_count(conn_1, 2)
    assert len(conn_0.get_streams()) == 2
    assert len(conn_1.get_streams()) == 2

    conn_0.remove_stream(stream_0_0)
    assert len(conn_0.get_streams()) == 1
    conn_0.remove_stream(stream_0_1)
    assert len(conn_0.get_streams()) == 0
    # Nothing happen if `stream_0_1` is not present or already removed.
    conn_0.remove_stream(stream_0_1)
