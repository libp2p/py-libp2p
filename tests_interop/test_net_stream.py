import asyncio

import pytest

from libp2p.network.stream.exceptions import StreamClosed, StreamEOF, StreamReset
from tests.constants import MAX_READ_LEN

DATA = b"data"


@pytest.mark.asyncio
async def test_net_stream_read_write(py_to_daemon_stream_pair, p2pds):
    stream_py, stream_daemon = py_to_daemon_stream_pair
    assert (
        stream_py.protocol_id is not None
        and stream_py.protocol_id == stream_daemon.stream_info.proto
    )
    await stream_py.write(DATA)
    assert (await stream_daemon.read(MAX_READ_LEN)) == DATA


@pytest.mark.asyncio
async def test_net_stream_read_after_remote_closed(py_to_daemon_stream_pair, p2pds):
    stream_py, stream_daemon = py_to_daemon_stream_pair
    await stream_daemon.write(DATA)
    await stream_daemon.close()
    await asyncio.sleep(0.01)
    assert (await stream_py.read(MAX_READ_LEN)) == DATA
    # EOF
    with pytest.raises(StreamEOF):
        await stream_py.read(MAX_READ_LEN)


@pytest.mark.asyncio
async def test_net_stream_read_after_local_reset(py_to_daemon_stream_pair, p2pds):
    stream_py, _ = py_to_daemon_stream_pair
    await stream_py.reset()
    with pytest.raises(StreamReset):
        await stream_py.read(MAX_READ_LEN)


@pytest.mark.parametrize("is_to_fail_daemon_stream", (True,))
@pytest.mark.asyncio
async def test_net_stream_read_after_remote_reset(py_to_daemon_stream_pair, p2pds):
    stream_py, _ = py_to_daemon_stream_pair
    await asyncio.sleep(0.01)
    with pytest.raises(StreamReset):
        await stream_py.read(MAX_READ_LEN)


@pytest.mark.asyncio
async def test_net_stream_write_after_local_closed(py_to_daemon_stream_pair, p2pds):
    stream_py, _ = py_to_daemon_stream_pair
    await stream_py.write(DATA)
    await stream_py.close()
    with pytest.raises(StreamClosed):
        await stream_py.write(DATA)


@pytest.mark.asyncio
async def test_net_stream_write_after_local_reset(py_to_daemon_stream_pair, p2pds):
    stream_py, stream_daemon = py_to_daemon_stream_pair
    await stream_py.reset()
    with pytest.raises(StreamClosed):
        await stream_py.write(DATA)


@pytest.mark.parametrize("is_to_fail_daemon_stream", (True,))
@pytest.mark.asyncio
async def test_net_stream_write_after_remote_reset(py_to_daemon_stream_pair, p2pds):
    stream_py, _ = py_to_daemon_stream_pair
    await asyncio.sleep(0.01)
    with pytest.raises(StreamClosed):
        await stream_py.write(DATA)
