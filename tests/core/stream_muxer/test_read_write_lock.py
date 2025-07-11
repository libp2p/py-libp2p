from unittest.mock import AsyncMock, MagicMock

import pytest
import trio

from libp2p.stream_muxer.mplex.mplex_stream import MplexStream, StreamID


@pytest.fixture
def stream_with_lock() -> tuple[MplexStream, trio.MemorySendChannel[bytes]]:
    muxed_conn = MagicMock()
    muxed_conn.send_message = AsyncMock()
    muxed_conn.streams_lock = trio.Lock()
    muxed_conn.streams = {}
    muxed_conn.get_remote_address = MagicMock(return_value=("127.0.0.1", 8000))

    send_chan: trio.MemorySendChannel[bytes]
    recv_chan: trio.MemoryReceiveChannel[bytes]
    send_chan, recv_chan = trio.open_memory_channel(0)

    dummy_stream_id = MagicMock(spec=StreamID)
    dummy_stream_id.is_initiator = True  # mock read-only property

    stream = MplexStream(
        name="test",
        stream_id=dummy_stream_id,
        muxed_conn=muxed_conn,
        incoming_data_channel=recv_chan,
    )
    return stream, send_chan


@pytest.mark.trio
async def test_writing_blocked_if_read_in_progress(
    stream_with_lock: tuple[MplexStream, trio.MemorySendChannel[bytes]],
) -> None:
    stream, _ = stream_with_lock
    log: list[str] = []

    async def reader() -> None:
        await stream.rw_lock.acquire_read()
        log.append("read_acquired")
        await trio.sleep(0.3)
        log.append("read_released")
        await stream.rw_lock.release_read()

    async def writer() -> None:
        await stream.rw_lock.acquire_write()
        log.append("write_acquired")
        await trio.sleep(0.1)
        log.append("write_released")
        stream.rw_lock.release_write()

    async with trio.open_nursery() as nursery:
        nursery.start_soon(reader)
        await trio.sleep(0.05)
        nursery.start_soon(writer)

    assert log == [
        "read_acquired",
        "read_released",
        "write_acquired",
        "write_released",
    ], f"Unexpected order: {log}"


@pytest.mark.trio
async def test_reading_blocked_if_write_in_progress(
    stream_with_lock: tuple[MplexStream, trio.MemorySendChannel[bytes]],
) -> None:
    stream, _ = stream_with_lock
    log: list[str] = []

    async def writer() -> None:
        await stream.rw_lock.acquire_write()
        log.append("write_acquired")
        await trio.sleep(0.3)
        log.append("write_released")
        stream.rw_lock.release_write()

    async def reader() -> None:
        await stream.rw_lock.acquire_read()
        log.append("read_acquired")
        await trio.sleep(0.1)
        log.append("read_released")
        await stream.rw_lock.release_read()

    async with trio.open_nursery() as nursery:
        nursery.start_soon(writer)
        await trio.sleep(0.05)
        nursery.start_soon(reader)

    assert log == [
        "write_acquired",
        "write_released",
        "read_acquired",
        "read_released",
    ], f"Unexpected order: {log}"


@pytest.mark.trio
async def test_multiple_reads_allowed_concurrently(
    stream_with_lock: tuple[MplexStream, trio.MemorySendChannel[bytes]],
) -> None:
    stream, _ = stream_with_lock
    log: list[str] = []

    async def read_task(i: int) -> None:
        await stream.rw_lock.acquire_read()
        log.append(f"read_{i}_acquired")
        await trio.sleep(0.2)
        log.append(f"read_{i}_released")
        await stream.rw_lock.release_read()

    async with trio.open_nursery() as nursery:
        for i in range(5):
            nursery.start_soon(read_task, i)

    acquires = [entry for entry in log if "acquired" in entry]
    releases = [entry for entry in log if "released" in entry]

    assert len(acquires) == 5 and len(releases) == 5, "Not all reads executed"
    assert all(
        log.index(acq) < min(log.index(rel) for rel in releases) for acq in acquires
    ), f"Reads didn't overlap properly: {log}"


@pytest.mark.trio
async def test_only_one_write_allowed(
    stream_with_lock: tuple[MplexStream, trio.MemorySendChannel[bytes]],
) -> None:
    stream, _ = stream_with_lock
    log: list[str] = []

    async def write_task(i: int) -> None:
        await stream.rw_lock.acquire_write()
        log.append(f"write_{i}_acquired")
        await trio.sleep(0.2)
        log.append(f"write_{i}_released")
        stream.rw_lock.release_write()

    async with trio.open_nursery() as nursery:
        for i in range(5):
            nursery.start_soon(write_task, i)

    active = 0
    for entry in log:
        if "acquired" in entry:
            active += 1
        elif "released" in entry:
            active -= 1
        assert active <= 1, f"More than one write active: {log}"
    assert active == 0, f"Write locks not properly released: {log}"


@pytest.mark.trio
async def test_interleaved_read_write_behavior(
    stream_with_lock: tuple[MplexStream, trio.MemorySendChannel[bytes]],
) -> None:
    stream, _ = stream_with_lock
    log: list[str] = []

    async def read(i: int) -> None:
        await stream.rw_lock.acquire_read()
        log.append(f"read_{i}_acquired")
        await trio.sleep(0.15)
        log.append(f"read_{i}_released")
        await stream.rw_lock.release_read()

    async def write(i: int) -> None:
        await stream.rw_lock.acquire_write()
        log.append(f"write_{i}_acquired")
        await trio.sleep(0.2)
        log.append(f"write_{i}_released")
        stream.rw_lock.release_write()

    async with trio.open_nursery() as nursery:
        nursery.start_soon(read, 1)
        await trio.sleep(0.05)
        nursery.start_soon(read, 2)
        await trio.sleep(0.05)
        nursery.start_soon(write, 1)
        await trio.sleep(0.05)
        nursery.start_soon(read, 3)
        await trio.sleep(0.05)
        nursery.start_soon(write, 2)

    read1_released = log.index("read_1_released")
    read2_released = log.index("read_2_released")
    write1_acquired = log.index("write_1_acquired")
    assert write1_acquired > read1_released and write1_acquired > read2_released, (
        f"write_1 acquired too early: {log}"
    )

    read3_acquired = log.index("read_3_acquired")
    read3_released = log.index("read_3_released")
    write1_released = log.index("write_1_released")
    assert read3_released < write1_acquired or read3_acquired > write1_released, (
        f"read_3 improperly overlapped with write_1: {log}"
    )

    write2_acquired = log.index("write_2_acquired")
    assert write2_acquired > write1_released, f"write_2 started too early: {log}"
